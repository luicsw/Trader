"""Shared upsert logic for provider profile+quote data -- used by both lookup_service and
refresh_service so refresh mechanics apply uniformly regardless of trigger source (NFR-1).
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import Company, CoverageTier, PriceBar


def latest_bar(db: Session, company_id: int) -> PriceBar | None:
    return db.scalar(
        select(PriceBar)
        .where(PriceBar.company_id == company_id)
        .order_by(PriceBar.ts.desc())
        .limit(1)
    )


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

    bar_ts = now.replace(minute=0, second=0, microsecond=0)
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
