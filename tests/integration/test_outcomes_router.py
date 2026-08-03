from datetime import datetime, timedelta, timezone

from app.config import settings
from app.db.models import AiAnalysis, AnalysisTrigger, Company, CoverageTier, PriceBar, Verdict


def _seed_evaluable_analysis(db, ticker, verdict, confidence, last_close, horizon_close):
    old_enough = datetime.now(timezone.utc) - timedelta(days=settings.verdict_outcome_horizon_days + 1)
    company = Company(ticker=ticker, coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    db.add(
        AiAnalysis(
            company_id=company.id,
            verdict=verdict,
            confidence=confidence,
            reasoning_text="test",
            price_targets={"buy_at_or_below": None, "sell_at_or_above": None, "stop_loss": None},
            hold_period_days={"min": None, "max": None, "note": None},
            cited_sources=[],
            context_snapshot={"prompt_data": {"price_summary": {"last_close": last_close}}},
            trigger=AnalysisTrigger.on_demand,
            generated_at=old_enough,
        )
    )
    db.add(
        PriceBar(
            company_id=company.id,
            ts=old_enough + timedelta(days=settings.verdict_outcome_horizon_days),
            interval="1d",
            close=horizon_close,
        )
    )
    db.commit()


def test_evaluate_outcomes_returns_summary_shape(client):
    response = client.post("/internal/evaluate-outcomes")

    assert response.status_code == 200
    assert set(response.json().keys()) == {"checked", "evaluated", "skipped"}


def test_track_record_empty_when_no_outcomes_evaluated_yet(client):
    response = client.get("/verdicts/track-record")

    assert response.status_code == 200
    assert response.json() == {"by_verdict": [], "by_confidence": []}


def test_track_record_reflects_evaluated_outcomes(client, db_session):
    _seed_evaluable_analysis(db_session, "ZTRA", Verdict.buy, confidence=0.8, last_close=100.0, horizon_close=110.0)
    client.post("/internal/evaluate-outcomes")

    response = client.get("/verdicts/track-record")

    assert response.status_code == 200
    body = response.json()
    buy_row = next(row for row in body["by_verdict"] if row["verdict"] == "buy")
    assert buy_row["count"] == 1
    assert buy_row["avg_price_change_pct"] == 10.0
    assert buy_row["pct_directionally_correct"] == 100.0
    high_confidence_row = next(row for row in body["by_confidence"] if row["bucket"] == "high (>=0.6)")
    assert high_confidence_row["count"] == 1
    assert high_confidence_row["pct_directionally_correct"] == 100.0
