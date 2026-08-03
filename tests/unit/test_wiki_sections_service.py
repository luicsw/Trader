from datetime import datetime, timezone

from app.db.models import Company, CoverageTier, NewsArticle, PriceBar, Sentiment, WikiSectionKey
from app.services import wiki_sections_service


def _company(**overrides) -> Company:
    fields = dict(
        id=1,
        ticker="AAPL",
        name=None,
        exchange=None,
        sector=None,
        market_cap=None,
        coverage_tier=CoverageTier.lookup,
    )
    fields.update(overrides)
    return Company(**fields)


def test_render_overview_thin_data_is_honest():
    company = _company()
    assert "not yet available" in wiki_sections_service.render_overview(company)


def test_render_overview_full_data():
    company = _company(name="Apple Inc", exchange="NASDAQ", sector="Technology", market_cap=3_000_000)
    overview = wiki_sections_service.render_overview(company)
    assert "Apple Inc" in overview
    assert "NASDAQ" in overview
    assert "Technology" in overview
    assert "3,000,000" in overview


def test_render_key_metrics_no_data():
    company = _company()
    assert wiki_sections_service.render_key_metrics(company, None) == "No price or metric data available yet."


def test_render_key_metrics_with_bar():
    company = _company(market_cap=100)
    bar = PriceBar(company_id=1, ts=None, interval="1d", open=1, high=12, low=8, close=10, volume=None)
    metrics = wiki_sections_service.render_key_metrics(company, bar)
    assert "Last close: 10.00" in metrics
    assert "Day range: 8.00 - 12.00" in metrics


def test_render_key_metrics_includes_technicals_when_available():
    company = _company()
    price_summary = {"change_1d_pct": 1.5, "change_1m_pct": None, "change_1y_pct": None}
    swing_levels = {"high_20d": 12.0, "low_20d": 8.0}

    metrics = wiki_sections_service.render_key_metrics(company, None, price_summary, swing_levels)

    assert "1D change: +1.50%" in metrics
    assert "20d range: 8.00 - 12.00" in metrics
    assert "1M change" not in metrics  # null values are omitted, not shown as "None"


def test_render_news_digest_no_articles_is_honest():
    assert wiki_sections_service.render_news_digest([]) == wiki_sections_service.NOT_YET_INGESTED[
        WikiSectionKey.news_digest
    ]


def test_render_news_digest_with_articles():
    article = NewsArticle(
        company_id=1,
        headline="Company announces record earnings",
        source="Reuters",
        published_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        sentiment=Sentiment.positive,
        url="https://example.com/a",
    )

    digest = wiki_sections_service.render_news_digest([article])

    assert "Company announces record earnings" in digest
    assert "(Reuters)" in digest
    assert "2026-01-15" in digest
    assert "[positive]" in digest


def test_render_sections_includes_not_yet_ingested_placeholders():
    sections = wiki_sections_service.render_sections(_company(), None)
    assert sections[WikiSectionKey.financials_summary] == wiki_sections_service.NOT_YET_INGESTED[
        WikiSectionKey.financials_summary
    ]
    assert sections[WikiSectionKey.news_digest] == wiki_sections_service.NOT_YET_INGESTED[
        WikiSectionKey.news_digest
    ]
    assert set(sections.keys()) == set(WikiSectionKey)


def test_render_sections_uses_real_news_when_provided():
    article = NewsArticle(company_id=1, headline="Real headline", url="https://example.com/b")

    sections = wiki_sections_service.render_sections(_company(), None, articles=[article])

    assert "Real headline" in sections[WikiSectionKey.news_digest]
