"""Integration tests run against a real Postgres (spec.md §10) -- each test gets its own
transaction that's rolled back afterward, so nothing persists in the shared dev database.
"""
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from app.db.models import ProviderCallLog
from app.db.session import engine


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
