"""Integration tests run against a real Postgres (spec.md §10) -- each test gets its own
transaction that's rolled back afterward, so nothing persists in the shared dev database.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, update
from sqlalchemy.orm import sessionmaker

from app.db.models import ChatMessage, Holding, ProviderCallLog, Watchlist
from app.db.session import engine, get_db
from app.main import app


@pytest.fixture
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    # rate_limiter/circuit_breaker read every already-committed row in provider_call_log,
    # not just rows this test writes -- any manual live testing against this same dev
    # database (e.g. a reliability drill) would otherwise silently poison every test that
    # depends on provider call history. Deleting existing rows here only affects this
    # test's transaction, which is rolled back below, so nothing is actually lost.
    session.execute(delete(ProviderCallLog))
    # analyze_scheduled/refresh_watchlist/list_watchlist all operate on "every active
    # watchlist entry" globally, not just rows a test creates -- a real ticker a user
    # actually adds via the running app (not just drill data) would otherwise leak into
    # tests expecting an empty/known watchlist, and worse, could get picked up by
    # analyze_scheduled and trigger a real Gemini call mid-test-run. Deactivating (not
    # deleting) pre-existing entries here only affects this test's transaction, rolled
    # back below, so real watchlist data is untouched once the test finishes.
    session.execute(update(Watchlist).values(active=False))
    # holdings_service.list_holdings() and chat_service.list_messages() are global reads by
    # design -- "all my positions", "the whole conversation" -- so unlike the ai_analyses
    # incident in Phase 4, their tests have no company_id to scope an assertion to and
    # legitimately assert on totals ("empty", "exactly the two I just seeded"). Once real
    # holdings and real chat history exist in this shared dev database (they do -- the app is
    # in actual use), those totals collide with genuine user data. Same reasoning and same
    # remedy as the Watchlist case above: neutralize pre-existing rows inside this test's
    # transaction, which is rolled back below, so real data is untouched once the test ends.
    session.execute(delete(ChatMessage))
    session.execute(delete(Holding))
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    """A TestClient wired to `db_session` instead of the app's real database connection, so
    HTTP-level router tests get the same rolled-back-transaction isolation as service-level
    tests -- otherwise every request would write real, permanently-committed rows to the
    shared dev database (see tests/integration/test_refresh_router.py's history for why that
    was a real, non-hypothetical problem).
    """

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
