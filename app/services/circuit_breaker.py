"""Per-provider circuit breaker (spec.md FR-5), computed statelessly from the most recent
`provider_call_log` rows rather than kept in memory -- same rationale as rate_limiter.py:
state must survive a Render process restart, and the log already records everything needed.

- closed: fewer than `circuit_breaker_failure_threshold` consecutive failures -- calls allowed.
- open: threshold consecutive failures, most recent one within the cooldown window -- skip
  calls to this provider.
- half_open: threshold consecutive failures, but cooldown has elapsed -- allow a probe call;
  a success flips back to closed on the next check, a failure restarts the cooldown.
"""
import enum
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import CallStatus, ProviderCallLog, ProviderName


class CircuitState(str, enum.Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


def get_state(db: Session, provider: ProviderName) -> CircuitState:
    threshold = settings.circuit_breaker_failure_threshold
    cooldown = timedelta(seconds=settings.circuit_breaker_cooldown_seconds)

    recent = db.scalars(
        select(ProviderCallLog)
        .where(ProviderCallLog.provider == provider)
        .order_by(ProviderCallLog.called_at.desc())
        .limit(threshold)
    ).all()

    if len(recent) < threshold or any(call.status == CallStatus.success for call in recent):
        return CircuitState.closed

    most_recent_failure_at = recent[0].called_at
    if datetime.now(timezone.utc) - most_recent_failure_at < cooldown:
        return CircuitState.open
    return CircuitState.half_open


def is_available(db: Session, provider: ProviderName) -> bool:
    return get_state(db, provider) != CircuitState.open
