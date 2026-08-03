from datetime import datetime, timedelta, timezone

from app.db.models import Company, CoverageTier, PriceBar
from app.services import ingest_service


def _seed_company(db, ticker="ZBAR"):
    company = Company(ticker=ticker, coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.commit()
    return company


def test_bar_count_zero_when_no_bars(db_session):
    company = _seed_company(db_session)

    assert ingest_service.bar_count(db_session, company.id) == 0


def test_bulk_upsert_bars_inserts_many_at_once(db_session):
    company = _seed_company(db_session)
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    bars = [
        {"ts": now - timedelta(days=i), "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}
        for i in range(10)
    ]

    ingest_service.bulk_upsert_bars(db_session, company.id, bars)
    db_session.commit()

    assert ingest_service.bar_count(db_session, company.id) == 10


def test_bulk_upsert_bars_updates_on_conflict_without_duplicating(db_session):
    company = _seed_company(db_session)
    ts = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    ingest_service.bulk_upsert_bars(db_session, company.id, [{"ts": ts, "close": 100}])
    db_session.commit()
    ingest_service.bulk_upsert_bars(db_session, company.id, [{"ts": ts, "close": 105}])
    db_session.commit()

    assert ingest_service.bar_count(db_session, company.id) == 1
    bar = db_session.query(PriceBar).filter_by(company_id=company.id).one()
    assert float(bar.close) == 105.0


def test_bulk_upsert_bars_empty_list_is_a_no_op(db_session):
    company = _seed_company(db_session)

    ingest_service.bulk_upsert_bars(db_session, company.id, [])
    db_session.commit()

    assert ingest_service.bar_count(db_session, company.id) == 0
