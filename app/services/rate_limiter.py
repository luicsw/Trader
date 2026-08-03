"""Per-provider rate limiting, budgeted conservatively below each provider's documented
free-tier cap (plan.md "Reliability mechanics"). Implemented as a sliding window counted
directly against `provider_call_log` rather than in-memory token buckets -- the persisted
log IS the state, so there's nothing to "seed" on a cold start and no budget is lost across
Render's frequent process restarts.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import CallStatus, ProviderCallLog, ProviderName

_BUDGETS = {
    ProviderName.finnhub: (
        "finnhub_rate_limit_per_window",
        "finnhub_rate_limit_window_seconds",
    ),
    ProviderName.alpha_vantage: (
        "alpha_vantage_rate_limit_per_window",
        "alpha_vantage_rate_limit_window_seconds",
    ),
    ProviderName.gemini: (
        "gemini_rate_limit_per_window",
        "gemini_rate_limit_window_seconds",
    ),
}


def allow(db: Session, provider: ProviderName, budget_fraction: float = 1.0) -> bool:
    """True if `provider` is under budget for its current window.

    `budget_fraction` lets lower-priority callers get throttled before the full budget is
    exhausted -- e.g. on-demand/critique Gemini calls check against a smaller fraction than
    scheduled ones, reserving headroom for higher-priority callers (spec.md FR-17, FR-20).
    """
    limit_attr, window_attr = _BUDGETS[provider]
    limit = getattr(settings, limit_attr) * budget_fraction
    window_seconds = getattr(settings, window_attr)
    since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    count = db.scalar(
        select(func.count())
        .select_from(ProviderCallLog)
        .where(ProviderCallLog.provider == provider, ProviderCallLog.called_at >= since)
    )
    return count < limit


def record_call(db: Session, provider: ProviderName, status: CallStatus) -> None:
    db.add(ProviderCallLog(provider=provider, status=status))
