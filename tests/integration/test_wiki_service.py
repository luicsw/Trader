from datetime import datetime, timezone

from app.db.models import Company, CoverageTier, NewsArticle, PriceBar, Sentiment, WikiSection, WikiSectionKey
from app.services import wiki_service


def test_assemble_returns_none_for_unknown_ticker(db_session):
    assert wiki_service.assemble(db_session, "NOPE") is None


def test_assemble_reads_company_bar_and_sections(db_session):
    now = datetime.now(timezone.utc)
    company = Company(
        ticker="ZZZZ",
        name="Zzz Corp",
        exchange="NASDAQ",
        sector="Technology",
        market_cap=123,
        coverage_tier=CoverageTier.lookup,
        last_profile_refresh_at=now,
    )
    db_session.add(company)
    db_session.flush()

    db_session.add(
        PriceBar(company_id=company.id, ts=now, interval="1d", open=1, high=2, low=0.5, close=1.5)
    )
    db_session.add(
        WikiSection(company_id=company.id, section_key=WikiSectionKey.overview, body="Zzz Corp overview.")
    )
    db_session.add(
        NewsArticle(
            company_id=company.id,
            headline="Zzz Corp news",
            url="https://example.com/zzz",
            published_at=now,
            sentiment=Sentiment.neutral,
        )
    )
    db_session.commit()

    wiki = wiki_service.assemble(db_session, "zzzz")

    assert wiki["ticker"] == "ZZZZ"
    assert wiki["name"] == "Zzz Corp"
    assert wiki["market_cap"] == 123.0
    assert wiki["latest_price"]["close"] == 1.5
    assert wiki["sections"]["overview"]["body"] == "Zzz Corp overview."
    assert "financials_summary" not in wiki["sections"]
    assert wiki["price_summary"]["last_close"] == 1.5
    assert wiki["recent_swing_levels"]["high_20d"] == 2.0
    assert len(wiki["recent_news"]) == 1
    assert wiki["recent_news"][0]["headline"] == "Zzz Corp news"
    assert wiki["recent_news"][0]["sentiment"] == "neutral"
