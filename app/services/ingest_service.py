"""Shared upsert logic for provider profile+quote data -- used by both lookup_service and
refresh_service so refresh mechanics apply uniformly regardless of trigger source (NFR-1).
"""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Company, CoverageTier, NewsArticle, PriceBar, Sentiment


def latest_bar(db: Session, company_id: int) -> PriceBar | None:
    return db.scalar(
        select(PriceBar)
        .where(PriceBar.company_id == company_id)
        .order_by(PriceBar.ts.desc())
        .limit(1)
    )


def recent_bars(db: Session, company_id: int, limit: int = 260) -> list[PriceBar]:
    """Most-recent-first, up to `limit` bars -- 260 covers roughly a year of trading days,
    which is what technicals_service's 1y-lookback/200d-moving-average needs at most.
    """
    return list(
        db.scalars(
            select(PriceBar)
            .where(PriceBar.company_id == company_id)
            .order_by(PriceBar.ts.desc())
            .limit(limit)
        ).all()
    )


def bar_count(db: Session, company_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(PriceBar).where(PriceBar.company_id == company_id)
    )


def bulk_upsert_bars(db: Session, company_id: int, bars: list[dict]) -> None:
    """Bulk ON CONFLICT upsert for historical backfill -- one statement for the whole batch
    instead of one round-trip per bar. Each conflicting row updates with its own values via
    EXCLUDED, unlike upsert_profile_and_quote's single-row upsert which can use a plain
    literal dict since there's only ever one row in play there.
    """
    if not bars:
        return

    stmt = pg_insert(PriceBar).values(
        [
            {
                "company_id": company_id,
                "ts": bar["ts"],
                "interval": "1d",
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "volume": bar.get("volume"),
            }
            for bar in bars
        ]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PriceBar.company_id, PriceBar.ts, PriceBar.interval],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    db.execute(stmt)


def upsert_profile_and_quote(db: Session, ticker: str, profile: dict, quote: dict) -> Company:
    now = datetime.now(timezone.utc)

    # Upsert via ON CONFLICT so a repeated call can never duplicate or corrupt a row (FR-4).
    # coverage_tier is intentionally excluded from the conflict update -- a watchlist-tier
    # company refreshed here must not be silently demoted back to lookup tier, and a
    # lookup-tier company isn't promoted just by being viewed.
    company_fields = {
        "name": profile.get("name"),
        "exchange": profile.get("exchange"),
        "sector": profile.get("sector"),
        "logo_url": profile.get("logo_url"),
        "market_cap": profile.get("market_cap"),
        "last_profile_refresh_at": now,
    }
    company_stmt = (
        pg_insert(Company)
        .values(ticker=ticker, coverage_tier=CoverageTier.lookup, **company_fields)
        .on_conflict_do_update(index_elements=[Company.ticker], set_=company_fields)
        .returning(Company.id)
    )
    company_id = db.execute(company_stmt).scalar_one()

    # Truncated to the day, not the hour: a "1d" bar is one row per trading day, so repeated
    # intraday refreshes upsert the SAME row (converging toward the day's true high/low as
    # Finnhub's intraday-running h/l fields update) instead of fragmenting into one row per
    # hour, which would silently break any lookback over "the last N days" (Phase 4 needs
    # real day-level history for swing-level/price-change computations).
    bar_ts = now.replace(hour=0, minute=0, second=0, microsecond=0)
    bar_fields = {
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
    }
    bar_stmt = (
        pg_insert(PriceBar)
        .values(company_id=company_id, ts=bar_ts, interval="1d", **bar_fields)
        .on_conflict_do_update(
            index_elements=[PriceBar.company_id, PriceBar.ts, PriceBar.interval],
            set_=bar_fields,
        )
    )
    db.execute(bar_stmt)

    return db.get(Company, company_id)


def upsert_news(db: Session, company_id: int, articles: list[dict]) -> None:
    """Upsert normalized article dicts (see providers/base.py DataProvider.get_news) via
    ON CONFLICT on (company_id, url) -- re-fetching the same article (e.g. it's still within
    the lookback window on the next refresh) updates in place rather than duplicating.
    """
    for article in articles:
        sentiment = Sentiment(article["sentiment"]) if article.get("sentiment") else None
        fields = {
            "headline": article["headline"],
            "summary": article.get("summary"),
            "source": article.get("source"),
            "published_at": article.get("published_at"),
            "sentiment": sentiment,
        }
        stmt = (
            pg_insert(NewsArticle)
            .values(company_id=company_id, url=article["url"], **fields)
            .on_conflict_do_update(
                index_elements=[NewsArticle.company_id, NewsArticle.url],
                set_=fields,
            )
        )
        db.execute(stmt)


def recent_news(db: Session, company_id: int, limit: int = 6) -> list[NewsArticle]:
    return list(
        db.scalars(
            select(NewsArticle)
            .where(NewsArticle.company_id == company_id)
            .order_by(NewsArticle.published_at.desc().nulls_last())
            .limit(limit)
        ).all()
    )
