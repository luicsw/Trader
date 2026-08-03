from unittest.mock import MagicMock

import httpx
import pytest
import respx

from app.config import settings
from app.db.models import AiAnalysis, AnalysisTrigger, Company, CoverageTier, Verdict
from app.services import ai_service

VERDICT_JSON = {
    "verdict": "buy",
    "confidence": 0.75,
    "reasoning": "Strong momentum and positive news.",
    "price_targets": {"buy_at_or_below": 100, "sell_at_or_above": 130, "stop_loss": 90},
    "hold_period_days": {"min": 30, "max": 90, "note": "until next earnings"},
    "cited_sources": [{"type": "price", "reference": "recent swing"}],
}

CRITIQUE_JSON = {
    "agrees_with_verdict_direction": True,
    "biggest_weakness": "Confidence may be overstated given thin fundamentals.",
    "revised_price_targets": {"buy_at_or_below": None, "sell_at_or_above": None, "stop_loss": None},
    "revised_confidence": 0.6,
    "rationale": "Data is directionally sound but thin on fundamentals.",
}


def _mock_finnhub_success(name="Router AI Co"):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NASDAQ"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 100, "o": 99, "h": 101, "l": 98, "pc": 99.5})
    )
    respx.get("https://finnhub.io/api/v1/company-news").mock(return_value=httpx.Response(200, json=[]))


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


def _mock_gemini_client(monkeypatch, return_value):
    mock_instance = MagicMock()
    mock_instance.generate_json.return_value = return_value
    monkeypatch.setattr(ai_service, "GeminiClient", MagicMock(return_value=mock_instance))


@respx.mock
def test_analyze_returns_verdict(client, monkeypatch):
    _mock_finnhub_success()
    _mock_gemini_client(monkeypatch, VERDICT_JSON)

    response = client.post("/companies/zrta/analyze")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "ZRTA"
    assert body["verdict"] == "buy"
    assert body["confidence"] == 0.75
    assert body["trigger"] == "on_demand"


@respx.mock
def test_analyze_returns_429_on_quota_exhaustion(client, monkeypatch, db_session):
    from datetime import datetime, timezone

    from app.db.models import CallStatus, ProviderCallLog, ProviderName

    _mock_finnhub_success()
    limit = settings.gemini_rate_limit_per_window
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        db_session.add(ProviderCallLog(provider=ProviderName.gemini, status=CallStatus.success, called_at=now))
    db_session.commit()

    response = client.post("/companies/zrtb/analyze")

    assert response.status_code == 429


def test_analyze_scheduled_returns_summary_shape(client):
    response = client.post("/internal/analyze-scheduled")

    assert response.status_code == 200
    assert set(response.json().keys()) == {"checked", "analyzed", "skipped", "failed"}


@respx.mock
def test_critique_works_for_watchlisted_ticker(client, db_session, monkeypatch):
    company = Company(ticker="ZRTC", name="Router Critique Co", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.flush()
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
    db_session.add(analysis)
    db_session.commit()
    _mock_gemini_client(monkeypatch, CRITIQUE_JSON)

    response = client.post(f"/companies/zrtc/critique?analysis_id={analysis.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_id"] == analysis.id
    assert body["agrees_with_verdict_direction"] is True


def test_critique_rejected_for_lookup_tier_ticker(client, db_session):
    company = Company(ticker="ZRTD", name="Lookup Only Co", coverage_tier=CoverageTier.lookup)
    db_session.add(company)
    db_session.flush()
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
    db_session.add(analysis)
    db_session.commit()

    response = client.post(f"/companies/zrtd/critique?analysis_id={analysis.id}")

    assert response.status_code == 400


def test_critique_returns_404_for_unknown_ticker(client):
    response = client.post("/companies/znope/critique?analysis_id=1")

    assert response.status_code == 404


def test_list_analyses_returns_empty_for_unknown_ticker(client):
    response = client.get("/companies/znope/analyses")

    assert response.status_code == 200
    assert response.json() == []


@respx.mock
def test_list_analyses_returns_history_with_nested_critiques(client, db_session, monkeypatch):
    company = Company(ticker="ZRTE", name="History Co", coverage_tier=CoverageTier.watchlist)
    db_session.add(company)
    db_session.flush()
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
    db_session.add(analysis)
    db_session.commit()
    _mock_gemini_client(monkeypatch, CRITIQUE_JSON)
    client.post(f"/companies/zrte/critique?analysis_id={analysis.id}")

    response = client.get("/companies/zrte/analyses")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == analysis.id
    assert len(body[0]["critiques"]) == 1
    assert body[0]["critiques"][0]["agrees_with_verdict_direction"] is True
