"""forecast_service -- multi-horizon (30/60/90/180/360-day) expected low/high price bands from
the second AI provider, Groq (Post-Phase-5 Addition #2, spec.md FR-30 to FR-33).

SHIPS DORMANT: with GROQ_API_KEY unset, generate_forecast() raises ForecastUnavailableError
*before* touching the rate limiter, the client, or the database -- so a missing key writes no
provider_call_log row and no job_runs row and is a complete non-event (spec.md NFR-9/FR-33a).
Reading history (list_forecasts) needs no provider at all and works regardless of key state.

Prompt assembly deliberately reuses ai_service's template helpers (wiki_to_prompt_data,
_fill_template, _extract_template_block) against the shared wiki_service.assemble() data, so
Groq -- exactly like Gemini -- can never reason over data the user can't also see, and there's
one mapping to keep correct, not two.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import CallStatus, Company, PriceForecast, ProviderName
from app.providers import groq_client
from app.providers.base import PermanentProviderError, ProviderError
from app.providers.groq_client import GroqClient
from app.services import ai_service, rate_limiter, wiki_service

EXPECTED_HORIZONS = [30, 60, 90, 180, 360]

REPO_ROOT = ai_service.REPO_ROOT
PROMPT_PATH = REPO_ROOT / "prompts" / "forecast_prompt_v1.md"
PROMPT_VERSION = "forecast_prompt_v1"


class ForecastUnavailableError(Exception):
    """Raised when the forecast feature is dormant because GROQ_API_KEY is unset (spec.md
    FR-33a). Deliberately distinct from ProviderError and QuotaExhaustedError: it's neither a
    failure nor a quota skip, it's the feature being switched off -- the caller turns it into a
    clear 503 that names the real blocker, never a generic 500 or a silent no-op."""


def build_forecast_prompt(db: Session, ticker: str) -> dict:
    """Returns {"prompt_text", "context_snapshot"}. Raises ValueError if the company doesn't
    exist yet -- the caller ensures it does first."""
    wiki = wiki_service.assemble(db, ticker)
    if wiki is None:
        raise ValueError(f"No wiki data found for {ticker!r} -- company must exist before forecast")

    prompt_md = PROMPT_PATH.read_text(encoding="utf-8")
    template = ai_service._extract_template_block(prompt_md)
    data = ai_service.wiki_to_prompt_data(wiki)
    prompt_text = ai_service._fill_template(template, data)

    context_snapshot = {
        "wiki_data": wiki,
        "prompt_data": data,
        "prompt_version": PROMPT_VERSION,
        "model": settings.groq_model,
    }
    return {"prompt_text": prompt_text, "context_snapshot": context_snapshot}


def generate_forecast(db: Session, ticker: str) -> list[PriceForecast]:
    """Generates and persists five append-only price_forecasts rows (one per horizon, FR-31).

    Dormant-first ordering matters: the key check comes before any limiter/network/DB work so a
    missing key is a true non-event (FR-33a). QuotaExhaustedError (reused from ai_service) is
    raised before any Groq call if Groq's own budget slice is spent -- Groq's bucket is
    independent of Gemini's (FR-33), so this can never be caused by verdict/critique usage.
    """
    if not groq_client.is_available(settings.groq_api_key):
        raise ForecastUnavailableError("Groq API key not configured")

    if not rate_limiter.allow(db, ProviderName.groq):
        raise ai_service.QuotaExhaustedError(f"Groq budget exhausted for forecast of {ticker!r}")

    prompt = build_forecast_prompt(db, ticker)
    client = GroqClient(settings.groq_api_key, settings.groq_model)

    try:
        raw = client.generate_json(prompt["prompt_text"])
    except ProviderError:
        rate_limiter.record_call(db, ProviderName.groq, CallStatus.failure)
        db.commit()
        raise

    rate_limiter.record_call(db, ProviderName.groq, CallStatus.success)

    forecasts = _parse_forecasts(raw)
    company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    rows = [
        PriceForecast(
            company_id=company.id,
            horizon_days=f["horizon_days"],
            expected_low=f["expected_low"],
            expected_high=f["expected_high"],
            confidence=f["confidence"],
            rationale=f["rationale"],
            model=settings.groq_model,
            trigger="on_demand",
        )
        for f in forecasts
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def _parse_forecasts(raw: dict) -> list[dict]:
    """Validates Groq's parsed JSON into exactly the five expected horizons. json_object mode
    guarantees syntactic validity but not the schema (spec.md forecast prompt note), so the
    shape is enforced here -- a bad payload is a PermanentProviderError (retrying won't fix a
    model that returned the wrong shape), surfaced to the caller as a clear 502, never a 500.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("forecasts"), list):
        raise PermanentProviderError("Groq forecast response missing a 'forecasts' array")

    by_horizon: dict[int, dict] = {}
    for item in raw["forecasts"]:
        if not isinstance(item, dict):
            continue
        try:
            horizon = int(item["horizon_days"])
            low = float(item["expected_low"])
            high = float(item["expected_high"])
            confidence = float(item["confidence"])
            rationale = str(item["rationale"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentProviderError(f"Groq forecast entry has a malformed field: {exc}") from exc

        if horizon not in EXPECTED_HORIZONS:
            continue  # ignore any stray horizon the model invents
        if high < low:
            raise PermanentProviderError(
                f"Groq forecast for {horizon}d has expected_high < expected_low"
            )
        by_horizon[horizon] = {
            "horizon_days": horizon,
            "expected_low": low,
            "expected_high": high,
            "confidence": confidence,
            "rationale": rationale,
        }

    missing = [h for h in EXPECTED_HORIZONS if h not in by_horizon]
    if missing:
        raise PermanentProviderError(f"Groq forecast is missing horizons: {missing}")

    return [by_horizon[h] for h in EXPECTED_HORIZONS]


def list_forecasts(db: Session, ticker: str) -> dict:
    """Latest forecast set + full history for the wiki-page panel. Works with no Groq key --
    reading history needs no provider (spec.md FR-33a) -- returning an empty structure when
    nothing has ever been generated. Grouped by generation timestamp so each "Generate
    Forecast" click is one set of five horizons.
    """
    company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if company is None:
        return {"ticker": ticker.upper(), "latest": None, "history": []}

    rows = db.scalars(
        select(PriceForecast)
        .where(PriceForecast.company_id == company.id)
        .order_by(PriceForecast.generated_at.desc(), PriceForecast.horizon_days.asc())
    ).all()

    generations: dict[str, dict] = {}
    for row in rows:
        key = row.generated_at.isoformat()
        gen = generations.setdefault(
            key, {"generated_at": key, "model": row.model, "trigger": row.trigger, "forecasts": []}
        )
        gen["forecasts"].append(
            {
                "horizon_days": row.horizon_days,
                "expected_low": row.expected_low,
                "expected_high": row.expected_high,
                "confidence": row.confidence,
                "rationale": row.rationale,
            }
        )

    # dict preserves insertion order, and rows came back newest-first, so the first generation
    # is the latest set.
    ordered = list(generations.values())
    for gen in ordered:
        gen["forecasts"].sort(key=lambda f: f["horizon_days"])
    return {
        "ticker": company.ticker,
        "latest": ordered[0] if ordered else None,
        "history": ordered,
    }
