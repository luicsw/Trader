import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier, Watchlist
from app.services import watchlist_service


def _mock_finnhub_success(name="Promoted Co"):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NASDAQ"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 5, "o": 4, "h": 6, "l": 3, "pc": 4.5})
    )


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)


@respx.mock
def test_promote_new_ticker_creates_company_and_watchlist_entry(db_session):
    _mock_finnhub_success()

    wiki = watchlist_service.promote(db_session, "zzq")

    assert wiki["ticker"] == "ZZQ"
    assert wiki["initial_refresh_ok"] is True
    company = db_session.query(Company).filter_by(ticker="ZZQ").one()
    assert company.coverage_tier == CoverageTier.watchlist
    entry = db_session.query(Watchlist).filter_by(company_id=company.id).one()
    assert entry.active is True
    assert entry.last_scheduled_refresh_at is not None


@respx.mock
def test_promote_is_idempotent(db_session):
    _mock_finnhub_success()

    watchlist_service.promote(db_session, "zzq")
    watchlist_service.promote(db_session, "zzq")

    company = db_session.query(Company).filter_by(ticker="ZZQ").one()
    entries = db_session.query(Watchlist).filter_by(company_id=company.id).all()
    assert len(entries) == 1


@respx.mock
def test_remove_reverts_coverage_tier_and_deletes_entry(db_session):
    _mock_finnhub_success()
    watchlist_service.promote(db_session, "zzq")

    watchlist_service.remove(db_session, "zzq")

    company = db_session.query(Company).filter_by(ticker="ZZQ").one()
    assert company.coverage_tier == CoverageTier.lookup
    assert db_session.query(Watchlist).filter_by(company_id=company.id).one_or_none() is None


@respx.mock
def test_remove_unknown_ticker_is_a_safe_no_op(db_session):
    watchlist_service.remove(db_session, "NOPE")  # must not raise
