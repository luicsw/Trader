"""APScheduler wiring -- calls the exact same service functions that their respective
POST /internal/* routes call (NFR-1). This only matters while the Render process happens to
be warm between cold starts; the GitHub Actions cron hitting those routes is what guarantees
freshness regardless of process lifetime (plan.md "Deployment Decision").
"""
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db.session import SessionLocal
from app.services import outcome_service, refresh_service, ticker_directory_service

_scheduler: BackgroundScheduler | None = None


def _run_refresh_job() -> None:
    db = SessionLocal()
    try:
        refresh_service.refresh_watchlist(db)
    finally:
        db.close()


def _run_evaluate_outcomes_job() -> None:
    db = SessionLocal()
    try:
        outcome_service.evaluate_pending_outcomes(db)
    finally:
        db.close()


def _run_refresh_ticker_directory_job() -> None:
    db = SessionLocal()
    try:
        ticker_directory_service.refresh_directory(db)
    finally:
        db.close()


def start() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return

    # A BackgroundScheduler's executor can't be reused after shutdown() -- calling start()
    # again on the same instance silently produces a scheduler that logs "cannot schedule
    # new futures after shutdown" on every tick and never actually runs a job. Building a
    # fresh instance here makes start()/shutdown() safe to cycle more than once in the same
    # process (previously only ever exercised once per process, so this never surfaced).
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _run_refresh_job,
        "interval",
        seconds=settings.scheduler_interval_seconds,
        id="refresh_watchlist",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_evaluate_outcomes_job,
        "interval",
        seconds=settings.outcome_scheduler_interval_seconds,
        id="evaluate_outcomes",
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_refresh_ticker_directory_job,
        "interval",
        seconds=settings.ticker_directory_refresh_interval_seconds,
        id="refresh_ticker_directory",
        replace_existing=True,
    )
    _scheduler.start()


def shutdown() -> None:
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
