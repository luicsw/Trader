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
from app.db.models import ChatMessage, ChatRole, Company, CallStatus, ProviderName
from app.providers.base import ProviderError
from app.providers.gemini_client import GeminiClient
from app.services import rate_limiter, wiki_service

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = REPO_ROOT / "prompts" / "chat_prompt_v1.md"
PROMPT_VERSION = "chat_prompt_v1"

# Bounds prompt size for a user tracking an unusually large number of companies -- a personal
# single-user tool realistically tracks far fewer than this, so the cap is a safety margin,
# not an expected limit.
MAX_TRACKED_COMPANIES = 40
MAX_HISTORY_MESSAGES = 20

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


def _build_grounding_context(db) -> list[dict]:
    companies = db.scalars(select(Company).order_by(Company.id).limit(MAX_TRACKED_COMPANIES)).all()
    context = []
    for company in companies:
        wiki = wiki_service.assemble(db, company.ticker)
        if wiki is not None:
            context.append(wiki)
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

    history = list_messages(db)[-MAX_HISTORY_MESSAGES:]

    user_row = ChatMessage(role=ChatRole.user, content=user_message)
    db.add(user_row)
    db.commit()

    prompt_md = PROMPT_PATH.read_text(encoding="utf-8")
    template = _extract_template_block(prompt_md)
    prompt_text = _fill_template(
        template,
        json.dumps(tracked, indent=2, default=str),
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
