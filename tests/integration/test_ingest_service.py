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


def test_bars_for_interval_returns_ascending_order_within_the_given_interval(db_session):
    company = _seed_company(db_session)
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    ingest_service.bulk_upsert_bars(
        db_session, company.id, [{"ts": now - timedelta(days=i), "close": i} for i in range(5)]
    )
    db_session.commit()

    bars = ingest_service.bars_for_interval(db_session, company.id, "1d", limit=5)

    assert [bar.ts for bar in bars] == sorted(bar.ts for bar in bars)


def test_bars_for_interval_excludes_other_intervals(db_session):
    company = _seed_company(db_session)
    ingest_service.record_live_quote(db_session, company.id, 10.0)

    assert ingest_service.bars_for_interval(db_session, company.id, "1d") == []
    assert len(ingest_service.bars_for_interval(db_session, company.id, "5m")) == 1


def test_record_live_quote_creates_a_bar_on_first_poll(db_session):
    company = _seed_company(db_session)

    bar = ingest_service.record_live_quote(db_session, company.id, 10.0)

    assert float(bar.open) == 10.0
    assert float(bar.high) == 10.0
    assert float(bar.low) == 10.0
    assert float(bar.close) == 10.0
    assert bar.interval == "5m"


def test_record_live_quote_widens_high_low_and_moves_close_within_the_same_bucket(db_session):
    company = _seed_company(db_session)
    ingest_service.record_live_quote(db_session, company.id, 10.0)

    ingest_service.record_live_quote(db_session, company.id, 12.0)
    bar = ingest_service.record_live_quote(db_session, company.id, 8.0)

    assert float(bar.open) == 10.0  # unchanged from the first poll in this bucket
    assert float(bar.high) == 12.0
    assert float(bar.low) == 8.0
    assert float(bar.close) == 8.0  # most recent poll wins
    assert ingest_service.bar_count(db_session, company.id) == 1  # same bucket, not a new row
