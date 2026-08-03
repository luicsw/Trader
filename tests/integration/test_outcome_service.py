from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.models import (
    AiAnalysis,
    AnalysisTrigger,
    Company,
    CoverageTier,
    JobRun,
    JobStatus,
    PriceBar,
    Verdict,
    VerdictOutcome,
)
from app.services import outcome_service


def _seed_analysis(db, ticker, verdict, generated_at, last_close_at_verdict=100.0):
    company = Company(ticker=ticker, coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    analysis = AiAnalysis(
        company_id=company.id,
        verdict=verdict,
        confidence=0.6,
        reasoning_text="test",
        price_targets={"buy_at_or_below": None, "sell_at_or_above": None, "stop_loss": None},
        hold_period_days={"min": None, "max": None, "note": None},
        cited_sources=[],
        context_snapshot={"prompt_data": {"price_summary": {"last_close": last_close_at_verdict}}},
        trigger=AnalysisTrigger.on_demand,
        generated_at=generated_at,
    )
    db.add(analysis)
    db.commit()
    return company, analysis


def _add_bar(db, company_id, ts, close):
    db.add(PriceBar(company_id=company_id, ts=ts, interval="1d", close=close))
    db.commit()


def test_evaluates_analysis_past_horizon_with_price_data(db_session):
    old_enough = datetime.now(timezone.utc) - timedelta(days=settings.verdict_outcome_horizon_days + 1)
    company, analysis = _seed_analysis(db_session, "ZOUT", Verdict.buy, old_enough, last_close_at_verdict=100.0)
    _add_bar(db_session, company.id, old_enough + timedelta(days=settings.verdict_outcome_horizon_days), 110.0)

    summary = outcome_service.evaluate_pending_outcomes(db_session)

    assert summary["checked"] == 1
    assert summary["evaluated"] == [analysis.id]
    outcome = db_session.query(VerdictOutcome).filter_by(analysis_id=analysis.id).one()
    assert outcome.price_change_pct == 10.0
    assert outcome.directionally_correct is True


def test_skips_analysis_not_old_enough(db_session):
    recent = datetime.now(timezone.utc) - timedelta(days=1)
    _seed_analysis(db_session, "ZOUT2", Verdict.hold, recent)

    summary = outcome_service.evaluate_pending_outcomes(db_session)

    assert summary == {"checked": 0, "evaluated": [], "skipped": []}


def test_skips_when_no_price_data_at_horizon_yet(db_session):
    old_enough = datetime.now(timezone.utc) - timedelta(days=settings.verdict_outcome_horizon_days + 1)
    company, analysis = _seed_analysis(db_session, "ZOUT3", Verdict.sell, old_enough)
    # no price bar added at/after the horizon

    summary = outcome_service.evaluate_pending_outcomes(db_session)

    assert summary["checked"] == 1
    assert summary["skipped"] == [analysis.id]
    assert db_session.query(VerdictOutcome).filter_by(analysis_id=analysis.id).one_or_none() is None


def test_does_not_re_evaluate_already_evaluated_analysis(db_session):
    old_enough = datetime.now(timezone.utc) - timedelta(days=settings.verdict_outcome_horizon_days + 1)
    company, analysis = _seed_analysis(db_session, "ZOUT4", Verdict.hold, old_enough, last_close_at_verdict=100.0)
    _add_bar(db_session, company.id, old_enough + timedelta(days=settings.verdict_outcome_horizon_days), 102.0)

    first = outcome_service.evaluate_pending_outcomes(db_session)
    second = outcome_service.evaluate_pending_outcomes(db_session)

    assert first["evaluated"] == [analysis.id]
    assert second == {"checked": 0, "evaluated": [], "skipped": []}
    assert db_session.query(VerdictOutcome).filter_by(analysis_id=analysis.id).count() == 1


def test_records_job_run(db_session):
    old_enough = datetime.now(timezone.utc) - timedelta(days=settings.verdict_outcome_horizon_days + 1)
    _seed_analysis(db_session, "ZOUT5", Verdict.hold, old_enough)

    outcome_service.evaluate_pending_outcomes(db_session)

    job = db_session.query(JobRun).filter_by(job_name="evaluate_outcomes").one()
    assert job.status == JobStatus.success
