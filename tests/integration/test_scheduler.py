"""app/jobs/scheduler.py had zero test coverage before this -- it's only ever been exercised
implicitly via the FastAPI lifespan, which none of the other tests trigger (they use a plain
TestClient(app), not `with TestClient(app)`, so lifespan startup/shutdown never runs during the
rest of the suite). This proves the wiring actually works: start() invokes
refresh_service.refresh_watchlist on an interval, shutdown() actually stops it.

refresh_watchlist itself is monkeypatched out -- this test is about the scheduler's wiring,
not refresh logic (already covered by tests/integration/test_refresh_service.py). The real
SessionLocal() connect/close in _run_refresh_job still happens, but nothing is queried or
written.
"""
import threading
import time

from app.config import settings
from app.jobs import scheduler
from app.services import outcome_service, refresh_service


def test_start_invokes_refresh_periodically_and_shutdown_stops_it(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_interval_seconds", 1)
    fired = threading.Event()
    calls = []

    def fake_refresh_watchlist(db):
        calls.append(1)
        fired.set()
        return {"checked": 0, "refreshed": [], "failed": []}

    monkeypatch.setattr(refresh_service, "refresh_watchlist", fake_refresh_watchlist)

    scheduler.start()
    try:
        assert fired.wait(timeout=5), "scheduler never invoked refresh_watchlist within 5s"
    finally:
        scheduler.shutdown()

    count_at_shutdown = len(calls)
    time.sleep(1.5)  # long enough for another 1s-interval tick to have fired, if it were going to
    assert len(calls) == count_at_shutdown, "job kept firing after shutdown()"


def test_start_also_invokes_evaluate_outcomes_periodically(monkeypatch):
    monkeypatch.setattr(settings, "scheduler_interval_seconds", 3600)  # keep the refresh job quiet
    monkeypatch.setattr(settings, "outcome_scheduler_interval_seconds", 1)
    fired = threading.Event()

    def fake_evaluate_pending_outcomes(db):
        fired.set()
        return {"checked": 0, "evaluated": [], "skipped": []}

    monkeypatch.setattr(outcome_service, "evaluate_pending_outcomes", fake_evaluate_pending_outcomes)

    scheduler.start()
    try:
        assert fired.wait(timeout=5), "scheduler never invoked evaluate_pending_outcomes within 5s"
    finally:
        scheduler.shutdown()
