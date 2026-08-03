from datetime import datetime, timezone

import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier
from app.services import ingest_service


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")


def test_price_history_returns_empty_for_unknown_ticker(client):
    response = client.get("/companies/NOPE/price-history")

    assert response.status_code == 200
    assert response.json() == []


def test_price_history_returns_bars_for_the_requested_interval(client, db_session):
    company = Company(ticker="ZPH", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.flush()
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    ingest_service.bulk_upsert_bars(db_session, company.id, [{"ts": now, "close": 100}])
    db_session.commit()

    response = client.get("/companies/ZPH/price-history?interval=1d")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["close"] == 100.0


@respx.mock
def test_live_quote_poll_returns_the_bar(client, db_session):
    company = Company(ticker="ZPH", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.commit()
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 33, "o": 32, "h": 34, "l": 31, "pc": 32})
    )

    response = client.post("/companies/ZPH/live-quote")

    assert response.status_code == 200
    assert response.json()["close"] == 33.0


def test_live_quote_poll_returns_404_for_unknown_ticker(client):
    response = client.post("/companies/NOPE/live-quote")

    assert response.status_code == 404


@respx.mock
def test_live_quote_poll_returns_503_when_quote_unavailable(client, db_session):
    company = Company(ticker="ZPH", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.commit()
    respx.get("https://finnhub.io/api/v1/quote").mock(return_value=httpx.Response(503))

    response = client.post("/companies/ZPH/live-quote")

    assert response.status_code == 503
