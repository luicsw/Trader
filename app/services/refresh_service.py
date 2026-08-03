"""refresh_watchlist(db) -- the single refresh function called identically by the cron-
triggered POST /internal/refresh route and by jobs/scheduler.py's APScheduler job (NFR-1),
so refresh logic exists exactly once regardless of what triggered it.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JobRun, JobStatus, Watchlist
from app.providers.base import ProviderError
from app.services import ingest_service, provider_orchestrator, wiki_sections_service


def refresh_watchlist(db: Session) -> dict:
    """Refreshes every active watchlist ticker currently due, per its own
    refresh_interval_minutes. Idempotent/safe no-op when nothing is due -- redundant cron
    and warm-process triggers overlapping in time simply both find nothing to do.
    """
    due = _due_entries(db)
    refreshed, failed = [], []

    for entry in due:
        ticker = entry.company.ticker
        ok = refresh_entry(db, entry, job_name_prefix="scheduled_refresh")
        (refreshed if ok else failed).append(ticker)

    return {"checked": len(due), "refreshed": refreshed, "failed": failed}


def refresh_entry(db: Session, entry: Watchlist, job_name_prefix: str = "scheduled_refresh") -> bool:
    """Refresh a single watchlist entry right now, regardless of due-ness, logging the
    outcome to job_runs. Returns True on success, False on failure -- never raises, so a
    failed refresh here can never crash the caller (scheduled cycle or watchlist promote).
    """
    ticker = entry.company.ticker
    try:
        _refresh_one(db, entry)
    except ProviderError as exc:
        db.add(JobRun(job_name=f"{job_name_prefix}:{ticker}", status=JobStatus.failure, error_message=str(exc)))
        db.commit()
        return False

    db.add(JobRun(job_name=f"{job_name_prefix}:{ticker}", status=JobStatus.success))
    db.commit()
    return True


def _due_entries(db: Session) -> list[Watchlist]:
    now = datetime.now(timezone.utc)
    entries = db.scalars(select(Watchlist).where(Watchlist.active.is_(True))).all()
    return [entry for entry in entries if _is_due(entry, now)]


def _is_due(entry: Watchlist, now: datetime) -> bool:
    if entry.last_scheduled_refresh_at is None:
        return True
    age = now - entry.last_scheduled_refresh_at
    return age >= timedelta(minutes=entry.refresh_interval_minutes)


def _refresh_one(db: Session, entry: Watchlist) -> None:
    ticker = entry.company.ticker
    result = provider_orchestrator.fetch_with_fallback(db, ticker)
    company = ingest_service.upsert_profile_and_quote(db, ticker, result["profile"], result["quote"])

    articles = provider_orchestrator.fetch_news_best_effort(db, ticker)
    ingest_service.upsert_news(db, company.id, articles)

    bar = ingest_service.latest_bar(db, company.id)
    wiki_sections_service.generate_sections(db, company, bar)

    entry.last_scheduled_refresh_at = datetime.now(timezone.utc)
