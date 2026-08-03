from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.models import CallStatus, ProviderCallLog, ProviderName
from app.services import circuit_breaker


def _log(db, status, called_at):
    db.add(ProviderCallLog(provider=ProviderName.finnhub, status=status, called_at=called_at))


def test_closed_when_no_history(db_session):
    assert circuit_breaker.get_state(db_session, ProviderName.finnhub) == circuit_breaker.CircuitState.closed
    assert circuit_breaker.is_available(db_session, ProviderName.finnhub) is True


def test_closed_when_failures_below_threshold(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(settings.circuit_breaker_failure_threshold - 1):
        _log(db_session, CallStatus.failure, now)
    db_session.commit()

    assert circuit_breaker.get_state(db_session, ProviderName.finnhub) == circuit_breaker.CircuitState.closed


def test_open_after_consecutive_failures_within_cooldown(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(settings.circuit_breaker_failure_threshold):
        _log(db_session, CallStatus.failure, now)
    db_session.commit()

    assert circuit_breaker.get_state(db_session, ProviderName.finnhub) == circuit_breaker.CircuitState.open
    assert circuit_breaker.is_available(db_session, ProviderName.finnhub) is False


def test_half_open_after_cooldown_elapses(db_session):
    stale = datetime.now(timezone.utc) - timedelta(
        seconds=settings.circuit_breaker_cooldown_seconds * 2
    )
    for _ in range(settings.circuit_breaker_failure_threshold):
        _log(db_session, CallStatus.failure, stale)
    db_session.commit()

    assert circuit_breaker.get_state(db_session, ProviderName.finnhub) == circuit_breaker.CircuitState.half_open
    assert circuit_breaker.is_available(db_session, ProviderName.finnhub) is True


def test_closed_when_most_recent_call_succeeded(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(settings.circuit_breaker_failure_threshold - 1):
        _log(db_session, CallStatus.failure, now)
    _log(db_session, CallStatus.success, now)
    db_session.commit()

    assert circuit_breaker.get_state(db_session, ProviderName.finnhub) == circuit_breaker.CircuitState.closed
