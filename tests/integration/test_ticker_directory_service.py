import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.config import settings
from app.db.models import JobRun, JobStatus, ProviderCallLog, TickerDirectory
from app.services import ticker_directory_service

LISTING_URL = "https://finnhub.io/api/v1/stock/symbol"


def _seed(db, rows):
    for row in rows:
        db.add(TickerDirectory(**row))
    db.flush()


def _count(db):
    return db.scalar(select(func.count()).select_from(TickerDirectory))


def _job_runs(db, status):
    # job_runs is append-only observability the conftest deliberately does not clear, and a real
    # refresh_ticker_directory row already exists in the dev DB (from the feature's live bulk
    # pull). So assert on the *delta* this call adds, not an absolute count -- robust regardless
    # of pre-existing rows, and won't go flaky the next time the job is run for real.
    return db.scalar(
        select(func.count())
        .select_from(JobRun)
        .where(JobRun.job_name == "refresh_ticker_directory", JobRun.status == status)
    )


@pytest.fixture(autouse=True)
def _configure_key(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")


# ---- search (local only, zero provider calls) ----------------------------------------

def test_search_prefers_symbol_prefix_then_shorter_symbol(db_session):
    _seed(
        db_session,
        [
            {"symbol": "AAPL", "name": "Apple Inc", "exchange": "XNAS", "security_type": "Common Stock"},
            {"symbol": "AAP", "name": "Advance Auto Parts", "exchange": "XNYS", "security_type": "Common Stock"},
            {"symbol": "AAPX", "name": "AAP Warrant", "exchange": "OOTC", "security_type": "Right"},
            {"symbol": "TSLA", "name": "Tesla Inc", "exchange": "XNAS", "security_type": "Common Stock"},
        ],
    )

    results = ticker_directory_service.search(db_session, "AAP")
    symbols = [r["symbol"] for r in results]

    # All AAP*-prefixed symbols returned; shorter symbol (AAP) ahead of AAPL/AAPX; TSLA excluded.
    assert symbols[:3] == ["AAP", "AAPL", "AAPX"]
    assert "TSLA" not in symbols


def test_search_matches_on_name_fragment(db_session):
    _seed(
        db_session,
        [
            {"symbol": "NVDA", "name": "NVIDIA Corp", "exchange": "XNAS", "security_type": "Common Stock"},
            {"symbol": "MSFT", "name": "Microsoft Corp", "exchange": "XNAS", "security_type": "Common Stock"},
        ],
    )

    results = ticker_directory_service.search(db_session, "nvidia")

    assert [r["symbol"] for r in results] == ["NVDA"]


def test_search_never_calls_a_provider(db_session):
    _seed(db_session, [{"symbol": "AAPL", "name": "Apple Inc", "exchange": "XNAS", "security_type": "Common Stock"}])

    ticker_directory_service.search(db_session, "AAP")

    # A per-keystroke autocomplete that spent live provider quota would be the whole bug this
    # feature exists to avoid (FR-34) -- assert it logs no provider call at all.
    assert db_session.scalar(select(func.count()).select_from(ProviderCallLog)) == 0


def test_search_blank_query_returns_empty(db_session):
    assert ticker_directory_service.search(db_session, "   ") == []


def test_search_respects_limit(db_session):
    _seed(
        db_session,
        [{"symbol": f"AA{i}", "name": f"Company {i}", "exchange": "XNAS", "security_type": "Common Stock"} for i in range(10)],
    )

    assert len(ticker_directory_service.search(db_session, "AA", limit=3)) == 3


# ---- refresh_directory (bulk pull) ---------------------------------------------------

@respx.mock
def test_refresh_directory_populates_and_is_idempotent(db_session):
    success_before = _job_runs(db_session, JobStatus.success)
    respx.get(LISTING_URL).mock(
        return_value=httpx.Response(
            200,
            json=[
                {"symbol": "AAPL", "description": "Apple Inc", "mic": "XNAS", "type": "Common Stock"},
                {"symbol": "MSFT", "description": "Microsoft Corp", "mic": "XNAS", "type": "Common Stock"},
                # Duplicate symbol (same symbol on a second MIC) -- must not raise a
                # cardinality violation in the ON CONFLICT batch.
                {"symbol": "AAPL", "description": "Apple Inc dup", "mic": "OOTC", "type": "Common Stock"},
            ],
        )
    )

    result = ticker_directory_service.refresh_directory(db_session)

    assert result == {"status": "ok", "upserted": 2}
    assert _count(db_session) == 2
    row = db_session.scalar(select(TickerDirectory).where(TickerDirectory.symbol == "AAPL"))
    assert row.name == "Apple Inc"  # first occurrence wins the dedupe

    # A success provider call + a success job_run are logged (NFR-4 observability). JobRun is
    # scoped to this job's name, not counted globally: the shared dev DB carries real job_runs
    # from actual app use, so a global count would collide (the project's recurring
    # test-isolation bug -- same remedy as the ai_analyses precedent, scope don't broaden).
    assert db_session.scalar(select(func.count()).select_from(ProviderCallLog)) == 1
    assert _job_runs(db_session, JobStatus.success) == success_before + 1

    # Second pull with a changed name updates in place rather than duplicating (idempotent).
    respx.get(LISTING_URL).mock(
        return_value=httpx.Response(
            200, json=[{"symbol": "AAPL", "description": "Apple Incorporated", "mic": "XNAS", "type": "Common Stock"}]
        )
    )
    ticker_directory_service.refresh_directory(db_session)

    assert _count(db_session) == 2
    row = db_session.scalar(select(TickerDirectory).where(TickerDirectory.symbol == "AAPL"))
    assert row.name == "Apple Incorporated"


def test_refresh_directory_skips_without_key(db_session, monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", None)
    skipped_before = _job_runs(db_session, JobStatus.skipped)

    result = ticker_directory_service.refresh_directory(db_session)

    assert result == {"status": "skipped", "upserted": 0}
    assert _count(db_session) == 0
    assert db_session.scalar(select(func.count()).select_from(ProviderCallLog)) == 0
    assert _job_runs(db_session, JobStatus.skipped) == skipped_before + 1


@respx.mock
def test_refresh_directory_failure_logs_and_does_not_raise(db_session):
    failure_before = _job_runs(db_session, JobStatus.failure)
    respx.get(LISTING_URL).mock(return_value=httpx.Response(500))

    result = ticker_directory_service.refresh_directory(db_session)

    assert result == {"status": "failed", "upserted": 0}
    assert _count(db_session) == 0
    # A failed call is still logged (it consumed a slot) and surfaced in job_runs (NFR-4).
    assert db_session.scalar(select(func.count()).select_from(ProviderCallLog)) == 1
    assert _job_runs(db_session, JobStatus.failure) == failure_before + 1
