"""promote/remove -- the watchlist tier transitions (spec.md FR-11, FR-12, FR-13).

The AI-analysis leg of FR-11 ("trigger initial refresh + an `initial`-trigger AI analysis")
is intentionally not implemented yet -- ai_service doesn't exist until Phase 4. Promote
triggers the refresh half now; the analysis call slots in here without re-architecting once
Phase 4 lands.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Company, CoverageTier, Watchlist
from app.services import lookup_service, refresh_service, wiki_service


def promote(db: Session, ticker: str) -> dict:
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        # One fetch-with-fallback pass to establish the company row before watchlisting it.
        lookup_service.get_or_fetch(db, ticker)
        company = db.scalar(select(Company).where(Company.ticker == ticker))

    entry = db.scalar(select(Watchlist).where(Watchlist.company_id == company.id))
    if entry is None:
        entry = Watchlist(
            company_id=company.id,
            refresh_interval_minutes=settings.watchlist_default_refresh_interval_minutes,
            active=True,
        )
        db.add(entry)
    else:
        entry.active = True
    company.coverage_tier = CoverageTier.watchlist
    db.commit()

    initial_refresh_ok = refresh_service.refresh_entry(db, entry, job_name_prefix="promote_refresh")

    wiki = wiki_service.assemble(db, ticker)
    assert wiki is not None, "just upserted this company -- assemble() must find it"
    return {**wiki, "initial_refresh_ok": initial_refresh_ok}


def remove(db: Session, ticker: str) -> None:
    """Idempotent no-op if `ticker` isn't watchlisted. Leaves the company row (and, once
    Phase 4 exists, its historical ai_analyses/ai_critiques rows) untouched -- only the
    watchlist entry is deleted and coverage_tier reverts to lookup (FR-12).
    """
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        return

    entry = db.scalar(select(Watchlist).where(Watchlist.company_id == company.id))
    if entry is not None:
        db.delete(entry)
    company.coverage_tier = CoverageTier.lookup
    db.commit()
