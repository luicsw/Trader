from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier, PriceBar, Watchlist
from app.services import ingest_service, watchlist_service


def _mock_finnhub_success(name="Promoted Co"):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NASDAQ"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 5, "o": 4, "h": 6, "l": 3, "pc": 4.5})
    )
    # News resolves via Finnhub so it never falls through to Alpha Vantage -- keeps AV call
    # counts in these tests isolated to backfill specifically, not conflated with news.
    respx.get("https://finnhub.io/api/v1/company-news").mock(return_value=httpx.Response(200, json=[]))


def _mock_alpha_vantage_daily_history(num_days=60):
    series = {}
    base = datetime.now(timezone.utc)
    for i in range(num_days):
        date_str = (base - timedelta(days=i)).strftime("%Y-%m-%d")
        series[date_str] = {"1. open": "5", "2. high": "6", "3. low": "4", "4. close": "5.5", "5. volume": "1000"}
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json={"Time Series (Daily)": series})
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


@respx.mock
def test_promote_backfills_new_ticker_when_alpha_vantage_configured(db_session, monkeypatch):
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "av-key")
    _mock_finnhub_success()
    _mock_alpha_vantage_daily_history(num_days=60)

    wiki = watchlist_service.promote(db_session, "zzq")

    assert wiki["backfilled"] is True
    company = db_session.query(Company).filter_by(ticker="ZZQ").one()
    # 60 backfilled bars + 1 from the initial refresh, deduped by (company_id, ts, interval)
    assert ingest_service.bar_count(db_session, company.id) >= 60
    # technicals should now be populated instead of null, since real swing-level history exists
    assert wiki["recent_swing_levels"]["high_20d"] is not None


@respx.mock
def test_promote_skips_backfill_when_already_enough_bars_exist(db_session, monkeypatch):
    monkeypatch.setattr(settings, "alpha_vantage_api_key", "av-key")
    _mock_finnhub_success()
    company = Company(ticker="ZZQ", coverage_tier=CoverageTier.lookup)
    db_session.add(company)
    db_session.flush()
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for i in range(settings.backfill_min_bars_threshold):
        db_session.add(PriceBar(company_id=company.id, ts=now - timedelta(days=i), interval="1d", close=1))
    db_session.commit()
    av_route = respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json={"Time Series (Daily)": {}})
    )

    wiki = watchlist_service.promote(db_session, "zzq")

    assert wiki["backfilled"] is False
    assert av_route.call_count == 0


def test_list_watchlist_empty(db_session):
    assert watchlist_service.list_watchlist(db_session) == []


@respx.mock
def test_list_watchlist_returns_active_entries_with_summary(db_session):
    _mock_finnhub_success(name="ZZQ Co")
    watchlist_service.promote(db_session, "zzq")

    summaries = watchlist_service.list_watchlist(db_session)

    assert len(summaries) == 1
    assert summaries[0]["ticker"] == "ZZQ"
    assert summaries[0]["name"] == "ZZQ Co"
    assert summaries[0]["latest_price"]["close"] == 5.0
    assert summaries[0]["latest_verdict"] is None  # no ai_analyses yet -- Phase 4 not exercised here


def test_list_watchlist_excludes_removed_tickers(db_session):
    company = Company(ticker="ZZR", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.flush()
    db_session.add(Watchlist(company_id=company.id, refresh_interval_minutes=20, active=False))
    db_session.commit()

    assert watchlist_service.list_watchlist(db_session) == []
