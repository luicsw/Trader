from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, CoverageTier, JobRun, JobStatus, NewsArticle, Watchlist
from app.services import refresh_service


def _mock_finnhub_success(name="Refreshed Co", news=None):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NASDAQ"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 42, "o": 40, "h": 43, "l": 39, "pc": 41})
    )
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=news or [])
    )


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)


def _make_watchlisted_company(db, ticker, last_scheduled_refresh_at=None, refresh_interval_minutes=20):
    company = Company(ticker=ticker, coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    db.add(
        Watchlist(
            company_id=company.id,
            refresh_interval_minutes=refresh_interval_minutes,
            last_scheduled_refresh_at=last_scheduled_refresh_at,
            active=True,
        )
    )
    db.commit()
    return company


@respx.mock
def test_refreshes_a_never_refreshed_ticker(db_session):
    _make_watchlisted_company(db_session, "AAA", last_scheduled_refresh_at=None)
    _mock_finnhub_success()

    summary = refresh_service.refresh_watchlist(db_session)

    assert summary == {"checked": 1, "refreshed": ["AAA"], "failed": []}
    company = db_session.query(Company).filter_by(ticker="AAA").one()
    assert company.name == "Refreshed Co"
    assert company.coverage_tier == CoverageTier.watchlist  # never demoted
    entry = db_session.query(Watchlist).filter_by(company_id=company.id).one()
    assert entry.last_scheduled_refresh_at is not None
    job = db_session.query(JobRun).filter_by(job_name="scheduled_refresh:AAA").one()
    assert job.status == JobStatus.success


@respx.mock
def test_skips_recently_refreshed_ticker(db_session):
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    _make_watchlisted_company(db_session, "BBB", last_scheduled_refresh_at=recent, refresh_interval_minutes=20)

    summary = refresh_service.refresh_watchlist(db_session)

    assert summary == {"checked": 0, "refreshed": [], "failed": []}


@respx.mock
def test_refreshes_a_ticker_past_its_interval(db_session):
    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    _make_watchlisted_company(db_session, "CCC", last_scheduled_refresh_at=stale, refresh_interval_minutes=20)
    _mock_finnhub_success()

    summary = refresh_service.refresh_watchlist(db_session)

    assert summary == {"checked": 1, "refreshed": ["CCC"], "failed": []}


@respx.mock
def test_inactive_watchlist_entries_are_never_refreshed(db_session):
    company = Company(ticker="DDD", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.flush()
    db_session.add(Watchlist(company_id=company.id, refresh_interval_minutes=20, active=False))
    db_session.commit()

    summary = refresh_service.refresh_watchlist(db_session)

    assert summary == {"checked": 0, "refreshed": [], "failed": []}


@respx.mock
def test_provider_failure_is_recorded_and_does_not_crash_the_cycle(db_session):
    _make_watchlisted_company(db_session, "EEE", last_scheduled_refresh_at=None)
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(return_value=httpx.Response(200, json={}))

    summary = refresh_service.refresh_watchlist(db_session)

    assert summary["checked"] == 1
    assert summary["refreshed"] == []
    assert summary["failed"] == ["EEE"]
    job = db_session.query(JobRun).filter_by(job_name="scheduled_refresh:EEE").one()
    assert job.status == JobStatus.failure
    assert job.error_message


@respx.mock
def test_refresh_persists_news_articles(db_session):
    _make_watchlisted_company(db_session, "FFF", last_scheduled_refresh_at=None)
    _mock_finnhub_success(
        news=[{"headline": "FFF wins new contract", "url": "https://example.com/fff-news", "datetime": 1735689600}]
    )

    refresh_service.refresh_watchlist(db_session)

    company = db_session.query(Company).filter_by(ticker="FFF").one()
    articles = db_session.query(NewsArticle).filter_by(company_id=company.id).all()
    assert len(articles) == 1
    assert articles[0].headline == "FFF wins new contract"
