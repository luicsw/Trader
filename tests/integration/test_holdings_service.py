import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier, Holding, Watchlist
from app.services import holdings_service


def _mock_finnhub_success(name="Holding Co"):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NASDAQ"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 15, "o": 14, "h": 16, "l": 13, "pc": 14})
    )
    respx.get("https://finnhub.io/api/v1/company-news").mock(return_value=httpx.Response(200, json=[]))


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)


@respx.mock
def test_upsert_creates_holding_and_auto_promotes_to_watchlist(db_session):
    _mock_finnhub_success()

    result = holdings_service.upsert(db_session, "zhc", shares=10, cost_basis_per_share=12.0)

    assert result["ticker"] == "ZHC"
    assert result["shares"] == 10.0
    assert result["cost_basis_per_share"] == 12.0
    company = db_session.query(Company).filter_by(ticker="ZHC").one()
    assert company.coverage_tier == CoverageTier.watchlist
    assert db_session.query(Watchlist).filter_by(company_id=company.id).one_or_none() is not None


@respx.mock
def test_upsert_computes_unrealized_gain_against_latest_price(db_session):
    _mock_finnhub_success()

    result = holdings_service.upsert(db_session, "zhc", shares=10, cost_basis_per_share=12.0)

    # latest close from the mocked quote is 15 -> (15 - 12) * 10 = 30
    assert result["latest_price"] == 15.0
    assert result["market_value"] == 150.0
    assert result["cost_basis_total"] == 120.0
    assert result["unrealized_gain"] == pytest.approx(30.0)
    assert result["unrealized_gain_pct"] == pytest.approx(25.0)


@respx.mock
def test_upsert_is_idempotent_and_overwrites_existing_holding(db_session):
    _mock_finnhub_success()
    holdings_service.upsert(db_session, "zhc", shares=10, cost_basis_per_share=12.0)

    holdings_service.upsert(db_session, "zhc", shares=20, cost_basis_per_share=13.5, notes="topped up")

    company = db_session.query(Company).filter_by(ticker="ZHC").one()
    holdings = db_session.query(Holding).filter_by(company_id=company.id).all()
    assert len(holdings) == 1
    assert holdings[0].shares == 20
    assert holdings[0].notes == "topped up"


@respx.mock
def test_upsert_does_not_repromote_already_active_watchlist_entry(db_session):
    _mock_finnhub_success()
    holdings_service.upsert(db_session, "zhc", shares=10, cost_basis_per_share=12.0)
    company = db_session.query(Company).filter_by(ticker="ZHC").one()
    entry = db_session.query(Watchlist).filter_by(company_id=company.id).one()
    original_refresh_at = entry.last_scheduled_refresh_at

    holdings_service.upsert(db_session, "zhc", shares=11, cost_basis_per_share=12.0)

    db_session.refresh(entry)
    assert entry.last_scheduled_refresh_at == original_refresh_at


def test_list_holdings_empty(db_session):
    assert holdings_service.list_holdings(db_session) == []


@respx.mock
def test_list_holdings_returns_all_positions(db_session):
    _mock_finnhub_success()

    holdings_service.upsert(db_session, "zhc", shares=10, cost_basis_per_share=12.0)

    summaries = holdings_service.list_holdings(db_session)
    assert len(summaries) == 1
    assert summaries[0]["ticker"] == "ZHC"
    assert summaries[0]["category"] == "Other"  # sector not set in this fixture


@respx.mock
def test_get_for_company_returns_none_without_a_holding(db_session):
    _mock_finnhub_success()
    from app.services import watchlist_service

    watchlist_service.promote(db_session, "zhc")
    company = db_session.query(Company).filter_by(ticker="ZHC").one()

    assert holdings_service.get_for_company(db_session, company.id) is None


@respx.mock
def test_remove_deletes_holding_but_leaves_watchlist_entry(db_session):
    _mock_finnhub_success()
    holdings_service.upsert(db_session, "zhc", shares=10, cost_basis_per_share=12.0)

    holdings_service.remove(db_session, "zhc")

    company = db_session.query(Company).filter_by(ticker="ZHC").one()
    assert db_session.query(Holding).filter_by(company_id=company.id).one_or_none() is None
    assert db_session.query(Watchlist).filter_by(company_id=company.id).one_or_none() is not None


def test_remove_unknown_ticker_is_a_safe_no_op(db_session):
    holdings_service.remove(db_session, "NOPE")  # must not raise
