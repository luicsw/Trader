"""APScheduler wiring -- calls the exact same refresh_service.refresh_watchlist() function
that POST /internal/refresh calls (NFR-1). This only matters while the Render process
happens to be warm between cold starts; the GitHub Actions cron hitting /internal/refresh
is what guarantees freshness regardless of process lifetime (plan.md "Deployment Decision").
"""
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db.session import SessionLocal
from app.services import refresh_service

_scheduler = BackgroundScheduler()


def _run_refresh_job() -> None:
    db = SessionLocal()
    try:
        refresh_service.refresh_watchlist(db)
    finally:
        db.close()


def start() -> None:
    if _scheduler.running:
        return
    _scheduler.add_job(
        _run_refresh_job,
        "interval",
        seconds=settings.scheduler_interval_seconds,
        id="refresh_watchlist",
        replace_existing=True,
    )
    _scheduler.start()


def shutdown() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
