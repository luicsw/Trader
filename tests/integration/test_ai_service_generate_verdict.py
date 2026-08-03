from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.db.models import (
    AiAnalysis,
    AnalysisTrigger,
    CallStatus,
    Company,
    CoverageTier,
    ProviderCallLog,
    ProviderName,
    Verdict,
    WikiSection,
    WikiSectionKey,
)
from app.providers.base import PermanentProviderError
from app.services import ai_service

VERDICT_JSON = {
    "verdict": "buy",
    "confidence": 0.8,
    "reasoning": "Strong momentum.",
    "price_targets": {"buy_at_or_below": 10, "sell_at_or_above": 15, "stop_loss": 8},
    "hold_period_days": {"min": 30, "max": 90, "note": None},
    "cited_sources": [{"type": "price", "reference": "recent swing"}],
}


def _seed_company(db, ticker="ZGEN"):
    company = Company(ticker=ticker, name="Gen Co", coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    db.add(WikiSection(company_id=company.id, section_key=WikiSectionKey.overview, body="Overview."))
    db.commit()
    return company


def _mock_gemini_client(monkeypatch, return_value=None, side_effect=None):
    mock_instance = MagicMock()
    if side_effect is not None:
        mock_instance.generate_json.side_effect = side_effect
    else:
        mock_instance.generate_json.return_value = return_value
    monkeypatch.setattr(ai_service, "GeminiClient", MagicMock(return_value=mock_instance))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    return mock_instance


def test_generate_verdict_persists_analysis(db_session, monkeypatch):
    _seed_company(db_session)
    _mock_gemini_client(monkeypatch, return_value=VERDICT_JSON)

    analysis = ai_service.generate_verdict(db_session, "ZGEN", AnalysisTrigger.on_demand)

    assert analysis.verdict == Verdict.buy
    assert analysis.confidence == 0.8
    assert analysis.trigger == AnalysisTrigger.on_demand
    assert analysis.context_snapshot["prompt_version"] == "verdict_prompt_v2"
    stored = db_session.query(AiAnalysis).filter_by(company_id=analysis.company_id).one()
    assert stored.id == analysis.id


def test_generate_verdict_records_success_in_provider_call_log(db_session, monkeypatch):
    _seed_company(db_session)
    _mock_gemini_client(monkeypatch, return_value=VERDICT_JSON)

    ai_service.generate_verdict(db_session, "ZGEN", AnalysisTrigger.scheduled)

    log = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.gemini).one()
    assert log.status == CallStatus.success


def test_generate_verdict_provider_error_propagates_and_logs_failure(db_session, monkeypatch):
    company = _seed_company(db_session)
    _mock_gemini_client(monkeypatch, side_effect=PermanentProviderError("bad json"))

    with pytest.raises(PermanentProviderError):
        ai_service.generate_verdict(db_session, "ZGEN", AnalysisTrigger.on_demand)

    assert db_session.query(AiAnalysis).filter_by(company_id=company.id).count() == 0
    log = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.gemini).one()
    assert log.status == CallStatus.failure


def test_on_demand_blocked_before_full_budget_exhausted_but_scheduled_still_allowed(db_session, monkeypatch):
    _seed_company(db_session)
    on_demand_limit = int(settings.gemini_rate_limit_per_window * settings.gemini_on_demand_budget_fraction)
    now = datetime.now(timezone.utc)
    for _ in range(on_demand_limit):
        db_session.add(ProviderCallLog(provider=ProviderName.gemini, status=CallStatus.success, called_at=now))
    db_session.commit()

    with pytest.raises(ai_service.QuotaExhaustedError):
        ai_service.generate_verdict(db_session, "ZGEN", AnalysisTrigger.on_demand)

    _mock_gemini_client(monkeypatch, return_value=VERDICT_JSON)
    analysis = ai_service.generate_verdict(db_session, "ZGEN", AnalysisTrigger.scheduled)
    assert analysis.trigger == AnalysisTrigger.scheduled


def test_scheduled_blocked_once_full_budget_exhausted(db_session):
    _seed_company(db_session)
    limit = settings.gemini_rate_limit_per_window
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        db_session.add(ProviderCallLog(provider=ProviderName.gemini, status=CallStatus.success, called_at=now))
    db_session.commit()

    with pytest.raises(ai_service.QuotaExhaustedError):
        ai_service.generate_verdict(db_session, "ZGEN", AnalysisTrigger.scheduled)
