from datetime import datetime, timezone
from unittest.mock import MagicMock

from app.config import settings
from app.db.models import (
    AiAnalysis,
    CallStatus,
    Company,
    CoverageTier,
    JobRun,
    JobStatus,
    ProviderCallLog,
    ProviderName,
    Watchlist,
    WikiSection,
    WikiSectionKey,
)
from app.services import ai_service

VERDICT_JSON = {
    "verdict": "hold",
    "confidence": 0.6,
    "reasoning": "Balanced outlook.",
    "price_targets": {"buy_at_or_below": None, "sell_at_or_above": None, "stop_loss": None},
    "hold_period_days": {"min": None, "max": None, "note": None},
    "cited_sources": [],
}


def _seed_watchlisted_company(db, ticker):
    company = Company(ticker=ticker, name=f"{ticker} Co", coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    db.add(WikiSection(company_id=company.id, section_key=WikiSectionKey.overview, body="Overview."))
    db.add(Watchlist(company_id=company.id, refresh_interval_minutes=20, active=True))
    db.commit()
    return company


def _mock_gemini_client(monkeypatch, return_value=VERDICT_JSON):
    mock_instance = MagicMock()
    mock_instance.generate_json.return_value = return_value
    monkeypatch.setattr(ai_service, "GeminiClient", MagicMock(return_value=mock_instance))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


def test_analyze_scheduled_analyzes_every_active_ticker(db_session, monkeypatch):
    company_a = _seed_watchlisted_company(db_session, "ZSCA")
    company_b = _seed_watchlisted_company(db_session, "ZSCB")
    _mock_gemini_client(monkeypatch)

    summary = ai_service.analyze_scheduled(db_session)

    assert summary["checked"] == 2
    assert set(summary["analyzed"]) == {"ZSCA", "ZSCB"}
    assert summary["skipped"] == []
    assert summary["failed"] == []
    company_ids = [company_a.id, company_b.id]
    assert db_session.query(AiAnalysis).filter(AiAnalysis.company_id.in_(company_ids)).count() == 2


def test_analyze_scheduled_ignores_inactive_entries(db_session, monkeypatch):
    company = Company(ticker="ZSCC", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.flush()
    db_session.add(Watchlist(company_id=company.id, refresh_interval_minutes=20, active=False))
    db_session.commit()

    summary = ai_service.analyze_scheduled(db_session)

    assert summary == {"checked": 0, "analyzed": [], "skipped": [], "failed": []}


def test_analyze_scheduled_skips_on_quota_exhaustion_without_crashing(db_session, monkeypatch):
    _seed_watchlisted_company(db_session, "ZSCD")
    limit = settings.gemini_rate_limit_per_window
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        db_session.add(ProviderCallLog(provider=ProviderName.gemini, status=CallStatus.success, called_at=now))
    db_session.commit()

    summary = ai_service.analyze_scheduled(db_session)

    assert summary["checked"] == 1
    assert summary["skipped"] == ["ZSCD"]
    assert summary["analyzed"] == []
    job = db_session.query(JobRun).filter_by(job_name="scheduled_analysis:ZSCD").one()
    assert job.status == JobStatus.skipped
