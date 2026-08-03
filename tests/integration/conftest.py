"""Integration tests run against a real Postgres (spec.md §10) -- each test gets its own
transaction that's rolled back afterward, so nothing persists in the shared dev database.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.db.models import ProviderCallLog
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
