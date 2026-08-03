from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier, Watchlist


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)


def test_internal_refresh_returns_summary_shape_with_nothing_due(client):
    response = client.post("/internal/refresh")

    assert response.status_code == 200
    assert response.json() == {"checked": 0, "refreshed": [], "failed": []}


@respx.mock
def test_internal_refresh_actually_refreshes_a_due_ticker(client, db_session):
    company = Company(ticker="RFR", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.flush()
    db_session.add(
        Watchlist(
            company_id=company.id,
            refresh_interval_minutes=20,
            last_scheduled_refresh_at=datetime.now(timezone.utc) - timedelta(hours=1),
            active=True,
        )
    )
    db_session.commit()
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": "Refreshed via router", "exchange": "NYSE"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 1, "o": 1, "h": 1, "l": 1, "pc": 1})
    )

    response = client.post("/internal/refresh")

    assert response.status_code == 200
    assert response.json() == {"checked": 1, "refreshed": ["RFR"], "failed": []}
