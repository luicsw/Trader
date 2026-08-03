"""ai_service.build_prompt(ticker) -- renders prompts/verdict_prompt_v1.md against
wiki_service.assemble()'s dict (spec.md FR-14). The AI must never see data the user can't
also see, so this maps wiki_service.assemble()'s exact output into the prompt template's
placeholder shape -- no separate data path.

Prompt template loading/filling deliberately duplicates scripts/test_gemini_prompt.py's
logic rather than importing from it -- that script is documented to have zero dependency on
the rest of the app (Phase 0's derisking constraint), so it can't import from here either,
and this can't import from scripts/ (not a package meant for runtime use).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.models import (
    AiAnalysis,
    AiCritique,
    AnalysisTrigger,
    CallStatus,
    Company,
    JobRun,
    JobStatus,
    ProviderName,
    Verdict,
    Watchlist,
)
from app.providers.base import ProviderError
from app.providers.gemini_client import GeminiClient
from app.services import rate_limiter, wiki_service


class QuotaExhaustedError(Exception):
    """Raised when the Gemini daily budget (or this trigger's reserved slice of it, per
    FR-17/FR-20's priority ordering) is exhausted -- deliberately distinct from
    ProviderError: this isn't a provider failure, it's an intentional, expected skip that
    callers must turn into a clear response (FR-16), never a generic 500.
    """

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "verdict_prompt_v2.md"
CRITIQUE_PROMPT_PATH = REPO_ROOT / "prompts" / "verdict_critique_prompt_v1.md"
PROMPT_VERSION = "verdict_prompt_v2"
CRITIQUE_PROMPT_VERSION = "verdict_critique_prompt_v1"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["buy", "hold", "sell"]},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "price_targets": {
            "type": "object",
            "properties": {
                "buy_at_or_below": {"type": "number", "nullable": True},
                "sell_at_or_above": {"type": "number", "nullable": True},
                "stop_loss": {"type": "number", "nullable": True},
            },
            "required": ["buy_at_or_below", "sell_at_or_above", "stop_loss"],
        },
        "hold_period_days": {
            "type": "object",
            "properties": {
                "min": {"type": "integer", "nullable": True},
                "max": {"type": "integer", "nullable": True},
                "note": {"type": "string", "nullable": True},
            },
            "required": ["min", "max", "note"],
        },
        "cited_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["news", "fundamental", "price", "metric"]},
                    "reference": {"type": "string"},
                },
                "required": ["type", "reference"],
            },
        },
    },
    "required": [
        "verdict",
        "confidence",
        "reasoning",
        "price_targets",
        "hold_period_days",
        "cited_sources",
    ],
}

CRITIQUE_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "agrees_with_verdict_direction": {"type": "boolean"},
        "biggest_weakness": {"type": "string"},
        "revised_price_targets": {
            "type": "object",
            "properties": {
                "buy_at_or_below": {"type": "number", "nullable": True},
                "sell_at_or_above": {"type": "number", "nullable": True},
                "stop_loss": {"type": "number", "nullable": True},
            },
            "required": ["buy_at_or_below", "sell_at_or_above", "stop_loss"],
        },
        "revised_confidence": {"type": "number", "nullable": True},
        "rationale": {"type": "string"},
    },
    "required": [
        "agrees_with_verdict_direction",
        "biggest_weakness",
        "revised_price_targets",
        "revised_confidence",
        "rationale",
    ],
}


def _extract_template_block(prompt_md: str) -> str:
    start = prompt_md.index("## Template") + len("## Template")
    fence_start = prompt_md.index("```", start) + 3
    fence_end = prompt_md.index("```", fence_start)
    return prompt_md[fence_start:fence_end].strip()


def _format_position_text(holding: dict | None, ticker: str) -> str:
    if holding is None:
        return f"No position -- the user does not currently hold any shares of {ticker}."

    gain_pct = holding.get("unrealized_gain_pct")
    gain_str = f"{gain_pct:+.1f}%" if gain_pct is not None else "unknown (no current price available)"
    acquired = f", acquired {holding['acquired_at']}" if holding.get("acquired_at") else ""
    notes = f" User notes: {holding['notes']}" if holding.get("notes") else ""
    return (
        f"The user holds {holding['shares']} shares at a cost basis of "
        f"${holding['cost_basis_per_share']:.2f}/share{acquired}. "
        f"Unrealized gain/loss: {gain_str}.{notes}"
    )


def wiki_to_prompt_data(wiki: dict) -> dict:
    """Maps wiki_service.assemble()'s dict into the prompt template's placeholder shape.
    `key_metrics`/`financials_summary_last_4_periods` are honestly thin against what
    Phase 0's fixtures used (no fundamentals table exists yet, see spec.md's Phase 4 scope
    decision) -- already validated as a case Gemini handles gracefully
    (scripts/fixtures/sample_wiki_thin.json also ships an empty financials array).
    """
    sections = wiki.get("sections", {})
    return {
        "ticker": wiki["ticker"],
        "company_name": wiki.get("name") or wiki["ticker"],
        "sector": wiki.get("sector") or "Unknown",
        "exchange": wiki.get("exchange") or "Unknown",
        "as_of_timestamp": wiki.get("last_updated") or datetime.now(timezone.utc).isoformat(),
        "position_text": _format_position_text(wiki.get("holding"), wiki["ticker"]),
        "overview_text": sections.get("overview", {}).get("body", ""),
        "key_metrics": {
            "market_cap_usd": wiki.get("market_cap"),
            "sector": wiki.get("sector"),
        },
        "price_summary": wiki.get("price_summary") or {},
        "recent_swing_levels": wiki.get("recent_swing_levels") or {},
        "financials_summary_last_4_periods": [],
        "news_digest_last_6": wiki.get("recent_news") or [],
        "risks_notes_text": sections.get("risks_notes", {}).get("body", ""),
    }


def _fill_template(template: str, data: dict) -> str:
    filled = template
    filled = filled.replace("{{TICKER}}", data["ticker"])
    filled = filled.replace("{{COMPANY_NAME}}", data["company_name"])
    filled = filled.replace("{{SECTOR}}", data["sector"])
    filled = filled.replace("{{EXCHANGE}}", data["exchange"])
    filled = filled.replace("{{AS_OF_TIMESTAMP}}", data["as_of_timestamp"])
    filled = filled.replace("{{POSITION_TEXT}}", data["position_text"])
    filled = filled.replace("{{OVERVIEW_TEXT}}", data["overview_text"])
    filled = filled.replace("{{KEY_METRICS_JSON}}", json.dumps(data["key_metrics"], indent=2))
    filled = filled.replace("{{PRICE_SUMMARY}}", json.dumps(data["price_summary"], indent=2))
    filled = filled.replace(
        "{{RECENT_SWING_LEVELS_JSON}}", json.dumps(data["recent_swing_levels"], indent=2)
    )
    financials = data["financials_summary_last_4_periods"]
    filled = filled.replace("{{FINANCIALS_PERIOD_COUNT}}", str(len(financials)))
    filled = filled.replace("{{FINANCIALS_SUMMARY_JSON}}", json.dumps(financials, indent=2))
    news = data["news_digest_last_6"]
    filled = filled.replace("{{NEWS_ITEM_COUNT}}", str(len(news)))
    filled = filled.replace("{{NEWS_DIGEST}}", json.dumps(news, indent=2, default=str))
    filled = filled.replace("{{RISKS_NOTES_TEXT}}", data["risks_notes_text"])
    return filled


def build_prompt(db, ticker: str) -> dict:
    """Returns {"prompt_text", "context_snapshot", "response_schema"}. Raises ValueError if
    the company doesn't exist yet -- the caller (analysis router/service) is responsible for
    ensuring it does before requesting an analysis.
    """
    wiki = wiki_service.assemble(db, ticker)
    if wiki is None:
        raise ValueError(f"No wiki data found for {ticker!r} -- company must exist before analysis")

    prompt_md = PROMPT_PATH.read_text(encoding="utf-8")
    template = _extract_template_block(prompt_md)
    data = wiki_to_prompt_data(wiki)
    prompt_text = _fill_template(template, data)

    context_snapshot = {
        "wiki_data": wiki,
        "prompt_data": data,
        "prompt_version": PROMPT_VERSION,
        "model": settings.gemini_model,
    }
    return {"prompt_text": prompt_text, "context_snapshot": context_snapshot, "response_schema": RESPONSE_SCHEMA}


def build_critique_prompt(db, ticker: str, original_verdict: dict) -> dict:
    """Same wiki data as build_prompt(), plus the specific ai_analyses row being critiqued."""
    wiki = wiki_service.assemble(db, ticker)
    if wiki is None:
        raise ValueError(f"No wiki data found for {ticker!r} -- company must exist before critique")

    critique_md = CRITIQUE_PROMPT_PATH.read_text(encoding="utf-8")
    template = _extract_template_block(critique_md)
    data = wiki_to_prompt_data(wiki)
    prompt_text = _fill_template(template, data)
    prompt_text = prompt_text.replace(
        "{{ORIGINAL_VERDICT_JSON}}", json.dumps(original_verdict, indent=2, default=str)
    )

    context_snapshot = {
        "wiki_data": wiki,
        "prompt_data": data,
        "original_verdict": original_verdict,
        "prompt_version": CRITIQUE_PROMPT_VERSION,
        "model": settings.gemini_model,
    }
    return {
        "prompt_text": prompt_text,
        "context_snapshot": context_snapshot,
        "response_schema": CRITIQUE_RESPONSE_SCHEMA,
    }


_TRIGGER_BUDGET_FRACTION = {
    AnalysisTrigger.scheduled: 1.0,
    AnalysisTrigger.on_demand: None,  # resolved from settings at call time
    AnalysisTrigger.initial: None,  # ad-hoc, same priority tier as on-demand
}


def generate_verdict(db, ticker: str, trigger: AnalysisTrigger) -> AiAnalysis:
    """Generates and persists a new ai_analyses row (FR-14, FR-15) -- append-only, never
    overwritten. Raises QuotaExhaustedError before ever calling Gemini if this trigger's
    budget slice is used up (FR-16/FR-17): scheduled gets the full daily budget, on-demand
    and initial are throttled at a smaller fraction of it so a burst of on-demand usage can
    never starve the scheduled batch.
    """
    budget_fraction = _TRIGGER_BUDGET_FRACTION[trigger]
    if budget_fraction is None:
        budget_fraction = settings.gemini_on_demand_budget_fraction

    if not rate_limiter.allow(db, ProviderName.gemini, budget_fraction):
        raise QuotaExhaustedError(f"Gemini budget exhausted for trigger={trigger.value}")

    prompt = build_prompt(db, ticker)
    client = GeminiClient(settings.gemini_api_key, settings.gemini_model)

    try:
        raw = client.generate_json(prompt["prompt_text"], prompt["response_schema"])
    except ProviderError:
        rate_limiter.record_call(db, ProviderName.gemini, CallStatus.failure)
        db.commit()
        raise

    rate_limiter.record_call(db, ProviderName.gemini, CallStatus.success)

    company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    analysis = AiAnalysis(
        company_id=company.id,
        verdict=Verdict(raw["verdict"]),
        confidence=raw["confidence"],
        reasoning_text=raw["reasoning"],
        price_targets=raw["price_targets"],
        hold_period_days=raw["hold_period_days"],
        cited_sources=raw["cited_sources"],
        context_snapshot=prompt["context_snapshot"],
        trigger=trigger,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def analyze_scheduled(db) -> dict:
    """Runs a scheduled analysis for every active watchlist ticker (spec.md FR-17) --
    cron-triggered once daily, so unlike refresh there's no per-ticker due-check: each call
    is "today's batch." Quota exhaustion skips (not fails) a ticker so the cycle never
    crashes and next cycle can retry it (FR-16); every outcome is recorded in job_runs.
    """
    entries = db.scalars(select(Watchlist).where(Watchlist.active.is_(True))).all()
    analyzed, skipped, failed = [], [], []

    for entry in entries:
        ticker = entry.company.ticker
        try:
            generate_verdict(db, ticker, AnalysisTrigger.scheduled)
        except QuotaExhaustedError as exc:
            db.add(JobRun(job_name=f"scheduled_analysis:{ticker}", status=JobStatus.skipped, error_message=str(exc)))
            db.commit()
            skipped.append(ticker)
            continue
        except ProviderError as exc:
            db.add(JobRun(job_name=f"scheduled_analysis:{ticker}", status=JobStatus.failure, error_message=str(exc)))
            db.commit()
            failed.append(ticker)
            continue

        entry.last_scheduled_analysis_at = datetime.now(timezone.utc)
        db.add(JobRun(job_name=f"scheduled_analysis:{ticker}", status=JobStatus.success))
        db.commit()
        analyzed.append(ticker)

    return {"checked": len(entries), "analyzed": analyzed, "skipped": skipped, "failed": failed}


def generate_critique(db, ticker: str, analysis_id: int) -> AiCritique:
    """Adversarial second-opinion pass (spec.md FR-18 to FR-20) -- always on-demand, and the
    lowest-priority consumer of the daily Gemini budget (checked against
    gemini_critique_budget_fraction, smaller than on-demand's slice). The watchlist-only
    restriction decided for this project (spec.md Open Decision #1) is enforced by the
    caller (the critique router), not here.
    """
    analysis = db.get(AiAnalysis, analysis_id)
    if analysis is None or analysis.company.ticker.upper() != ticker.upper():
        raise ValueError(f"No ai_analyses row {analysis_id} found for {ticker!r}")

    if not rate_limiter.allow(db, ProviderName.gemini, settings.gemini_critique_budget_fraction):
        raise QuotaExhaustedError(f"Gemini budget exhausted for critique of {ticker!r}")

    original_verdict = {
        "verdict": analysis.verdict.value,
        "confidence": analysis.confidence,
        "reasoning": analysis.reasoning_text,
        "price_targets": analysis.price_targets,
        "hold_period_days": analysis.hold_period_days,
        "cited_sources": analysis.cited_sources,
    }
    prompt = build_critique_prompt(db, ticker, original_verdict)
    client = GeminiClient(settings.gemini_api_key, settings.gemini_model)

    try:
        raw = client.generate_json(prompt["prompt_text"], prompt["response_schema"])
    except ProviderError:
        rate_limiter.record_call(db, ProviderName.gemini, CallStatus.failure)
        db.commit()
        raise

    rate_limiter.record_call(db, ProviderName.gemini, CallStatus.success)

    critique = AiCritique(
        analysis_id=analysis.id,
        agrees_with_verdict_direction=raw["agrees_with_verdict_direction"],
        biggest_weakness=raw["biggest_weakness"],
        revised_price_targets=raw["revised_price_targets"],
        revised_confidence=raw.get("revised_confidence"),
        rationale=raw["rationale"],
    )
    db.add(critique)
    db.commit()
    db.refresh(critique)
    return critique
