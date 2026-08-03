import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier, Watchlist


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)


def _mock_finnhub_success(name="Watchlist Co"):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NYSE"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 50, "o": 48, "h": 52, "l": 47, "pc": 49})
    )


@respx.mock
def test_promote_adds_to_watchlist(client, db_session):
    _mock_finnhub_success()

    response = client.post("/watchlist/wtc/promote")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "WTC"
    assert body["initial_refresh_ok"] is True

    company = db_session.query(Company).filter_by(ticker="WTC").one()
    assert company.coverage_tier == CoverageTier.watchlist
    assert db_session.query(Watchlist).filter_by(company_id=company.id).one_or_none() is not None


@respx.mock
def test_promote_then_remove_reverts_tier(client, db_session):
    _mock_finnhub_success()
    client.post("/watchlist/wtc/promote")

    response = client.delete("/watchlist/wtc")

    assert response.status_code == 200
    assert response.json() == {"ticker": "WTC", "removed": True}
    company = db_session.query(Company).filter_by(ticker="WTC").one()
    assert company.coverage_tier == CoverageTier.lookup
    assert db_session.query(Watchlist).filter_by(company_id=company.id).one_or_none() is None


@respx.mock
def test_promote_returns_502_when_ticker_unfetchable(client):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={})
    )

    response = client.post("/watchlist/badticker/promote")

    assert response.status_code == 502


def test_remove_unknown_ticker_is_a_safe_no_op(client):
    response = client.delete("/watchlist/nope")

    assert response.status_code == 200
    assert response.json() == {"ticker": "NOPE", "removed": True}
