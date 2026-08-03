"""promote/remove -- the watchlist tier transitions (spec.md FR-11, FR-12, FR-13).

The AI-analysis leg of FR-11 ("trigger initial refresh + an `initial`-trigger AI analysis")
is intentionally not implemented yet -- ai_service doesn't exist until Phase 4. Promote
triggers the refresh half now; the analysis call slots in here without re-architecting once
Phase 4 lands.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AiAnalysis, Company, CoverageTier, Watchlist
from app.services import (
    ingest_service,
    lookup_service,
    provider_orchestrator,
    refresh_service,
    sector_taxonomy,
    wiki_sections_service,
    wiki_service,
)


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
    backfilled = _backfill_if_needed(db, company, ticker)

    wiki = wiki_service.assemble(db, ticker)
    assert wiki is not None, "just upserted this company -- assemble() must find it"
    return {**wiki, "initial_refresh_ok": initial_refresh_ok, "backfilled": backfilled}


def _backfill_if_needed(db: Session, company: Company, ticker: str) -> bool:
    """One-time historical backfill (provider_orchestrator.backfill_price_history) so
    swing-level/moving-average technicals are usable immediately instead of taking weeks to
    accumulate one bar at a time. Skipped if the company already has enough history --
    idempotent, so re-promoting a previously-tracked ticker doesn't spend Alpha Vantage's
    scarce daily budget for nothing.
    """
    if ingest_service.bar_count(db, company.id) >= settings.backfill_min_bars_threshold:
        return False

    bars = provider_orchestrator.backfill_price_history(db, ticker)
    if not bars:
        return False

    ingest_service.bulk_upsert_bars(db, company.id, bars)
    db.commit()

    latest = ingest_service.latest_bar(db, company.id)
    wiki_sections_service.generate_sections(db, company, latest)
    db.commit()
    return True


def list_watchlist(db: Session) -> list[dict]:
    """Summary view for the dashboard grid (FR-21/T5.3) -- deliberately thin (no full wiki
    assembly per ticker, which would mean N news/technicals queries for one screen); the
    wiki page itself is where a ticker's full detail lives.
    """
    entries = db.scalars(select(Watchlist).where(Watchlist.active.is_(True))).all()

    summaries = []
    for entry in entries:
        company = entry.company
        latest_bar = ingest_service.latest_bar(db, company.id)
        latest_analysis = db.scalar(
            select(AiAnalysis)
            .where(AiAnalysis.company_id == company.id)
            .order_by(AiAnalysis.generated_at.desc())
            .limit(1)
        )
        summaries.append(
            {
                "ticker": company.ticker,
                "name": company.name,
                "sector": company.sector,
                "category": sector_taxonomy.categorize(company.sector),
                "logo_url": company.logo_url,
                "last_updated": company.last_profile_refresh_at.isoformat()
                if company.last_profile_refresh_at
                else None,
                "latest_price": {
                    "close": float(latest_bar.close) if latest_bar.close is not None else None,
                    "ts": latest_bar.ts.isoformat(),
                }
                if latest_bar
                else None,
                "latest_verdict": {
                    "verdict": latest_analysis.verdict.value,
                    "confidence": latest_analysis.confidence,
                    "generated_at": latest_analysis.generated_at.isoformat(),
                }
                if latest_analysis
                else None,
            }
        )
    return summaries


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
