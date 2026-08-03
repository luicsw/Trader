from datetime import datetime, timedelta, timezone

import httpx
import respx

from app.db.models import Company, CoverageTier, NewsArticle
from app.services import lookup_service


def _mock_finnhub(with_news=False):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Yyy Inc",
                "exchange": "NYSE",
                "finnhubIndustry": "Software",
                "logo": "https://example.com/logo.png",
                "marketCapitalization": 456,
            },
        )
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"o": 9, "h": 11, "l": 8, "c": 10, "pc": 9.5})
    )
    news = (
        [{"headline": "Yyy Inc launches new product", "url": "https://example.com/yyy-news", "datetime": 1735689600}]
        if with_news
        else []
    )
    respx.get("https://finnhub.io/api/v1/company-news").mock(return_value=httpx.Response(200, json=news))


@respx.mock
def test_get_or_fetch_fetches_and_persists_new_ticker(db_session):
    _mock_finnhub()

    wiki = lookup_service.get_or_fetch(db_session, "yyyy")

    assert wiki["ticker"] == "YYYY"
    assert wiki["name"] == "Yyy Inc"
    assert wiki["latest_price"]["close"] == 10.0
    assert "Yyy Inc" in wiki["sections"]["overview"]["body"]
    assert wiki["sections"]["financials_summary"]["body"] == (
        "No financial statement data has been ingested for this company yet."
    )

    company = db_session.query(Company).filter_by(ticker="YYYY").one()
    assert company.coverage_tier == CoverageTier.lookup


@respx.mock
def test_get_or_fetch_serves_fresh_row_without_refetching(db_session):
    _mock_finnhub()
    lookup_service.get_or_fetch(db_session, "yyyy")
    assert respx.calls.call_count == 3  # profile + quote + news

    lookup_service.get_or_fetch(db_session, "yyyy")
    assert respx.calls.call_count == 3  # no new provider calls -- served from Postgres


@respx.mock
def test_get_or_fetch_refetches_when_stale(db_session):
    _mock_finnhub()
    lookup_service.get_or_fetch(db_session, "yyyy")
    assert respx.calls.call_count == 3  # profile + quote + news

    company = db_session.query(Company).filter_by(ticker="YYYY").one()
    company.last_profile_refresh_at = datetime.now(timezone.utc) - timedelta(hours=2)
    db_session.commit()

    lookup_service.get_or_fetch(db_session, "yyyy")
    assert respx.calls.call_count == 6


@respx.mock
def test_get_or_fetch_persists_news_articles(db_session):
    _mock_finnhub(with_news=True)

    lookup_service.get_or_fetch(db_session, "yyyy")

    company = db_session.query(Company).filter_by(ticker="YYYY").one()
    articles = db_session.query(NewsArticle).filter_by(company_id=company.id).all()
    assert len(articles) == 1
    assert articles[0].headline == "Yyy Inc launches new product"
