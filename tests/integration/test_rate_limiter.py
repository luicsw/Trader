from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.models import CallStatus, ProviderCallLog, ProviderName
from app.services import rate_limiter


def test_allow_true_when_no_calls_logged(db_session):
    assert rate_limiter.allow(db_session, ProviderName.finnhub) is True


def test_allow_false_once_budget_is_exhausted(db_session):
    limit = settings.finnhub_rate_limit_per_window
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        db_session.add(ProviderCallLog(provider=ProviderName.finnhub, status=CallStatus.success, called_at=now))
    db_session.commit()

    assert rate_limiter.allow(db_session, ProviderName.finnhub) is False


def test_allow_ignores_calls_outside_the_window(db_session):
    limit = settings.finnhub_rate_limit_per_window
    window = settings.finnhub_rate_limit_window_seconds
    stale = datetime.now(timezone.utc) - timedelta(seconds=window * 2)
    for _ in range(limit):
        db_session.add(ProviderCallLog(provider=ProviderName.finnhub, status=CallStatus.success, called_at=stale))
    db_session.commit()

    assert rate_limiter.allow(db_session, ProviderName.finnhub) is True


def test_providers_have_independent_budgets(db_session):
    limit = settings.finnhub_rate_limit_per_window
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        db_session.add(ProviderCallLog(provider=ProviderName.finnhub, status=CallStatus.success, called_at=now))
    db_session.commit()

    assert rate_limiter.allow(db_session, ProviderName.finnhub) is False
    assert rate_limiter.allow(db_session, ProviderName.alpha_vantage) is True


def test_record_call_persists_a_row(db_session):
    rate_limiter.record_call(db_session, ProviderName.finnhub, CallStatus.failure)
    db_session.commit()

    rows = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.finnhub).all()
    assert len(rows) == 1
    assert rows[0].status == CallStatus.failure
