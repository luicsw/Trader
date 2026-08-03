import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier, PriceBar
from app.services import live_price_service


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")


def _seed_company(db, ticker="ZLIV"):
    company = Company(ticker=ticker, coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.commit()
    return company


@respx.mock
def test_poll_and_record_creates_a_5m_bar_from_the_quote(db_session):
    company = _seed_company(db_session)
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 25.5, "o": 24, "h": 26, "l": 23, "pc": 24.5})
    )

    bar = live_price_service.poll_and_record(db_session, company)

    assert bar is not None
    assert float(bar.close) == 25.5
    stored = db_session.query(PriceBar).filter_by(company_id=company.id, interval="5m").one()
    assert float(stored.close) == 25.5


@respx.mock
def test_poll_and_record_returns_none_when_quote_fails(db_session):
    company = _seed_company(db_session)
    respx.get("https://finnhub.io/api/v1/quote").mock(return_value=httpx.Response(503))

    assert live_price_service.poll_and_record(db_session, company) is None
    assert db_session.query(PriceBar).filter_by(company_id=company.id).count() == 0
