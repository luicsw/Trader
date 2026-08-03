from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.db.models import (
    AiAnalysis,
    AiCritique,
    AnalysisTrigger,
    CallStatus,
    Company,
    CoverageTier,
    ProviderCallLog,
    ProviderName,
    Verdict,
)
from app.services import ai_service, rate_limiter

CRITIQUE_JSON = {
    "agrees_with_verdict_direction": True,
    "biggest_weakness": "Confidence is too high given thin data.",
    "revised_price_targets": {"buy_at_or_below": None, "sell_at_or_above": None, "stop_loss": None},
    "revised_confidence": 0.3,
    "rationale": "Data is too thin to support this confidence level.",
}


def _seed_analysis(db, ticker="ZCRIT"):
    company = Company(ticker=ticker, name="Crit Co", coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    analysis = AiAnalysis(
        company_id=company.id,
        verdict=Verdict.hold,
        confidence=0.5,
        reasoning_text="thin data",
        price_targets={"buy_at_or_below": None, "sell_at_or_above": None, "stop_loss": None},
        hold_period_days={"min": None, "max": None, "note": None},
        cited_sources=[],
        context_snapshot={},
        trigger=AnalysisTrigger.on_demand,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return company, analysis


def _mock_gemini_client(monkeypatch, return_value=CRITIQUE_JSON):
    mock_instance = MagicMock()
    mock_instance.generate_json.return_value = return_value
    monkeypatch.setattr(ai_service, "GeminiClient", MagicMock(return_value=mock_instance))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


def test_generate_critique_persists_critique(db_session, monkeypatch):
    _, analysis = _seed_analysis(db_session)
    _mock_gemini_client(monkeypatch)

    critique = ai_service.generate_critique(db_session, "ZCRIT", analysis.id)

    assert critique.analysis_id == analysis.id
    assert critique.agrees_with_verdict_direction is True
    assert critique.revised_confidence == 0.3
    stored = db_session.query(AiCritique).filter_by(analysis_id=analysis.id).one()
    assert stored.id == critique.id


def test_generate_critique_raises_for_unknown_analysis_id(db_session):
    _seed_analysis(db_session)

    with pytest.raises(ValueError):
        ai_service.generate_critique(db_session, "ZCRIT", 999999)


def test_generate_critique_raises_for_mismatched_ticker(db_session):
    _, analysis = _seed_analysis(db_session, ticker="ZCRIT")
    _seed_analysis(db_session, ticker="ZOTHER")

    with pytest.raises(ValueError):
        ai_service.generate_critique(db_session, "ZOTHER", analysis.id)


def test_generate_critique_respects_lowest_priority_budget(db_session, monkeypatch):
    _, analysis = _seed_analysis(db_session)
    critique_limit = int(settings.gemini_rate_limit_per_window * settings.gemini_critique_budget_fraction)
    now = datetime.now(timezone.utc)
    for _ in range(critique_limit):
        db_session.add(ProviderCallLog(provider=ProviderName.gemini, status=CallStatus.success, called_at=now))
    db_session.commit()

    with pytest.raises(ai_service.QuotaExhaustedError):
        ai_service.generate_critique(db_session, "ZCRIT", analysis.id)

    # on-demand (a higher-priority tier) should still be allowed at this same usage level
    assert rate_limiter.allow(db_session, ProviderName.gemini, settings.gemini_on_demand_budget_fraction)
