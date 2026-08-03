from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.config import settings
from app.db.models import CallStatus, ProviderCallLog, ProviderName
from app.providers.base import PermanentProviderError
from app.services import provider_orchestrator


def _mock_finnhub_success():
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": "Finnhub Co", "exchange": "NYSE"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 10, "o": 9, "h": 11, "l": 8, "pc": 9.5})
    )


def _mock_alpha_vantage_success():
    def responder(request):
        if request.url.params.get("function") == "OVERVIEW":
            return httpx.Response(200, json={"Symbol": "X", "Name": "AV Co", "Exchange": "NASDAQ"})
        return httpx.Response(200, json={"Global Quote": {"05. price": "20"}})

    respx.get("https://www.alphavantage.co/query").mock(side_effect=responder)


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "av-key")


@respx.mock
def test_uses_finnhub_when_healthy(db_session):
    _mock_finnhub_success()

    result = provider_orchestrator.fetch_with_fallback(db_session, "AAPL")

    assert result["provider"] == ProviderName.finnhub
    assert result["profile"]["name"] == "Finnhub Co"
    logs = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.finnhub).all()
    assert len(logs) == 2
    assert all(log.status == CallStatus.success for log in logs)


@respx.mock
def test_falls_back_to_alpha_vantage_on_permanent_finnhub_error(db_session):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={})
    )  # empty -> permanent error
    _mock_alpha_vantage_success()

    result = provider_orchestrator.fetch_with_fallback(db_session, "AAPL")

    assert result["provider"] == ProviderName.alpha_vantage
    assert result["profile"]["name"] == "AV Co"
    finnhub_logs = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.finnhub).all()
    assert len(finnhub_logs) == 1  # permanent error -- no retry
    assert finnhub_logs[0].status == CallStatus.failure


@respx.mock
def test_retries_transient_errors_before_falling_back(db_session):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(return_value=httpx.Response(503))
    _mock_alpha_vantage_success()

    result = provider_orchestrator.fetch_with_fallback(db_session, "AAPL")

    assert result["provider"] == ProviderName.alpha_vantage
    finnhub_logs = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.finnhub).all()
    assert len(finnhub_logs) == 3  # stop_after_attempt(3)
    assert all(log.status == CallStatus.failure for log in finnhub_logs)


@respx.mock
def test_skips_provider_with_open_circuit(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(settings.circuit_breaker_failure_threshold):
        db_session.add(ProviderCallLog(provider=ProviderName.finnhub, status=CallStatus.failure, called_at=now))
    db_session.commit()
    finnhub_route = respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": "should not be called"})
    )
    _mock_alpha_vantage_success()

    result = provider_orchestrator.fetch_with_fallback(db_session, "AAPL")

    assert result["provider"] == ProviderName.alpha_vantage
    assert finnhub_route.call_count == 0


@respx.mock
def test_skips_provider_once_rate_limited(db_session):
    now = datetime.now(timezone.utc)
    for _ in range(settings.finnhub_rate_limit_per_window):
        db_session.add(ProviderCallLog(provider=ProviderName.finnhub, status=CallStatus.success, called_at=now))
    db_session.commit()
    finnhub_route = respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": "should not be called"})
    )
    _mock_alpha_vantage_success()

    result = provider_orchestrator.fetch_with_fallback(db_session, "AAPL")

    assert result["provider"] == ProviderName.alpha_vantage
    assert finnhub_route.call_count == 0


@respx.mock
def test_raises_when_all_providers_fail(db_session):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://www.alphavantage.co/query").mock(return_value=httpx.Response(200, json={}))

    with pytest.raises(PermanentProviderError):
        provider_orchestrator.fetch_with_fallback(db_session, "AAPL")
