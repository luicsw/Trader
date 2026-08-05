"""chat_service.send_message() -- grounded AI chat (Post-Phase-5 addition, per the user's
explicit decision: "grounded to tracked stocks only"). Every reply is restricted to
companies the user has actually looked up in this app (any row in `companies` -- watchlist,
holdings, and one-off searches all create exactly this kind of row via
lookup_service.get_or_fetch), using the same wiki_service.assemble() data the user sees on
each company's own wiki page. The prompt explicitly forbids reaching for Gemini's
general/training knowledge or discussing a company outside this set -- "best among what
you're tracking," never a live market-wide scan.
"""
import json
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.db.models import AiAnalysis, ChatMessage, ChatRole, Company, CallStatus, ProviderName
from app.providers.base import ProviderError
from app.providers.gemini_client import GeminiClient
from app.services import rate_limiter, wiki_service

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "chat_prompt_v1.md"
PROMPT_VERSION = "chat_prompt_v1"

# Prompt-size bounds live in config (settings.chat_*) rather than here: they are a
# quality-vs-tokens tradeoff the user should be able to tune without a code change, exactly like
# the Gemini budget fractions. See app/config.py for what each one costs.

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
}


class QuotaExhaustedError(Exception):
    """Gemini's chat budget slice is exhausted -- distinct from ProviderError, same as
    ai_service.QuotaExhaustedError: an expected, clear skip, not a provider failure.
    """


class NoTrackedCompaniesError(Exception):
    """Raised when the user isn't tracking anything yet -- there is nothing grounded to talk
    about, and the caller should surface this as a clear message rather than letting the
    model improvise an answer with no real data behind it.
    """


def _extract_template_block(prompt_md: str) -> str:
    start = prompt_md.index("## Template") + len("## Template")
    fence_start = prompt_md.index("```", start) + 3
    fence_end = prompt_md.index("```", fence_start)
    return prompt_md[fence_start:fence_end].strip()


def _truncate(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _latest_verdicts(db, company_ids: list[int]) -> dict[int, dict]:
    """Latest ai_analyses row per company, in one DISTINCT ON query rather than one query per
    company. The chat prompt has always instructed the model to ground its comparisons in
    "each company's latest verdict", but assemble() -- shaped for the wiki page, where the
    verdict banner is fetched separately -- never carried one, so that instruction referred to
    data that wasn't in the payload. Cheap to include, and it's the whole point of asking the
    chat to compare tracked companies.
    """
    if not company_ids:
        return {}

    rows = db.scalars(
        select(AiAnalysis)
        .where(AiAnalysis.company_id.in_(company_ids))
        .distinct(AiAnalysis.company_id)
        .order_by(AiAnalysis.company_id, AiAnalysis.generated_at.desc())
    ).all()
    return {
        row.company_id: {
            "verdict": row.verdict.value,
            "confidence": row.confidence,
            "price_targets": row.price_targets,
            "hold_period_days": row.hold_period_days,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        }
        for row in rows
    }


def _slim_for_grounding(wiki: dict, latest_verdict: dict | None) -> dict:
    """Trims wiki_service.assemble()'s dict down to what the model can actually reason with.

    Chat builds the largest prompt in this app -- one entry per tracked company, reassembled
    on *every* message -- so this is the one call site whose payload grows with how much the
    user tracks, and the one most likely to hit a token-per-minute limit or crowd out the
    on-demand analyses the daily budget is reserved for.

    assemble() is shaped for the wiki *page*: the frontend needs the logo, the article URLs,
    and the rendered `wiki_sections` prose. Three of those sections restate, in prose, data
    that is already in the payload as structured numbers:

      - `sections.news_digest`    -> the same headlines already listed in `recent_news`
      - `sections.key_metrics`    -> `latest_price` / `market_cap` / `sector` / `price_summary`
      - `sections.overview`       -> `name` / `exchange` / `sector` / `market_cap`

    Sending both copies costs tokens on every message and teaches the model nothing the
    structured fields don't already say. Dropped here rather than in `wiki_service.assemble()`
    itself, which stays the single shared read path (FR-10) the wiki route and every other AI
    caller depend on -- this is a subset of what the user can see, so the grounding guarantee
    is unaffected.

    Also dropped: `logo_url` (unusable by a text model), `coverage_tier` (internal
    bookkeeping), and each article's `url` -- citations are resolved server-side from
    prompt-assigned reference ids (spec.md FR-48), so the model never needs the URL, and
    shouldn't be handed one it could echo into a reply as if it had read the page.
    """
    return {
        "ticker": wiki["ticker"],
        "name": wiki.get("name"),
        "exchange": wiki.get("exchange"),
        "sector": wiki.get("sector"),
        "category": wiki.get("category"),
        "market_cap": wiki.get("market_cap"),
        "description": _truncate(wiki.get("description"), settings.chat_description_chars),
        "last_updated": wiki.get("last_updated"),
        "latest_price": wiki.get("latest_price"),
        "price_summary": wiki.get("price_summary"),
        "recent_swing_levels": wiki.get("recent_swing_levels"),
        "holding": wiki.get("holding"),
        "latest_verdict": latest_verdict,
        "recent_news": [
            {
                "headline": article.get("headline"),
                "summary": _truncate(article.get("summary"), settings.chat_article_summary_chars),
                "source": article.get("source"),
                "published_at": article.get("published_at"),
                "sentiment": article.get("sentiment"),
            }
            for article in (wiki.get("recent_news") or [])[
                : settings.chat_news_articles_per_company
            ]
        ],
    }


def _build_grounding_context(db) -> list[dict]:
    companies = db.scalars(
        select(Company).order_by(Company.id).limit(settings.chat_max_tracked_companies)
    ).all()
    verdicts = _latest_verdicts(db, [company.id for company in companies])

    context = []
    for company in companies:
        wiki = wiki_service.assemble(db, company.ticker)
        if wiki is not None:
            context.append(_slim_for_grounding(wiki, verdicts.get(company.id)))
    return context


def _format_history(messages: list[ChatMessage]) -> str:
    if not messages:
        return "(no previous messages)"
    speaker = {ChatRole.user: "User", ChatRole.assistant: "Assistant"}
    return "\n".join(f"{speaker[m.role]}: {m.content}" for m in messages)


def _fill_template(template: str, tracked_json: str, history_text: str, user_message: str) -> str:
    filled = template
    filled = filled.replace("{{TRACKED_COMPANIES_JSON}}", tracked_json)
    filled = filled.replace("{{CHAT_HISTORY}}", history_text)
    filled = filled.replace("{{USER_MESSAGE}}", user_message)
    return filled


def list_messages(db) -> list[ChatMessage]:
    return list(db.scalars(select(ChatMessage).order_by(ChatMessage.created_at)).all())


def send_message(db, user_message: str) -> ChatMessage:
    """Persists the user's message, then the assistant's reply, and returns the assistant
    row. Raises NoTrackedCompaniesError/QuotaExhaustedError/ProviderError before persisting
    anything if the request can't be grounded/afforded/fulfilled -- the user's own message is
    only ever recorded once a reply is actually being attempted.
    """
    tracked = _build_grounding_context(db)
    if not tracked:
        raise NoTrackedCompaniesError(
            "You aren't tracking any companies yet -- add one to your watchlist or holdings, "
            "or look one up first, then ask again."
        )

    if not rate_limiter.allow(db, ProviderName.gemini, settings.gemini_chat_budget_fraction):
        raise QuotaExhaustedError("Gemini budget exhausted for chat")

    history = list_messages(db)[-settings.chat_max_history_messages :]

    user_row = ChatMessage(role=ChatRole.user, content=user_message)
    db.add(user_row)
    db.commit()

    prompt_md = PROMPT_PATH.read_text(encoding="utf-8")
    template = _extract_template_block(prompt_md)
    prompt_text = _fill_template(
        template,
        # Compact separators, not indent=2: this blob is the bulk of the prompt and scales with
        # the number of tracked companies, so the pretty-printing whitespace is paid for on
        # every message. The model parses either form identically.
        json.dumps(tracked, separators=(",", ":"), default=str),
        _format_history(history),
        user_message,
    )

    client = GeminiClient(settings.gemini_api_key, settings.gemini_model)
    try:
        raw = client.generate_json(prompt_text, RESPONSE_SCHEMA)
    except ProviderError:
        rate_limiter.record_call(db, ProviderName.gemini, CallStatus.failure)
        db.commit()
        raise

    rate_limiter.record_call(db, ProviderName.gemini, CallStatus.success)

    assistant_row = ChatMessage(role=ChatRole.assistant, content=raw["reply"])
    db.add(assistant_row)
    db.commit()
    db.refresh(assistant_row)
    return assistant_row
