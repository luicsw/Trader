from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.db.models import (
    Company,
    CoverageTier,
    JobRun,
    PriceForecast,
    ProviderCallLog,
    ProviderName,
    WikiSection,
    WikiSectionKey,
)
from app.services import forecast_service

FORECAST_JSON = {
    "forecasts": [
        {"horizon_days": 30, "expected_low": 100, "expected_high": 115, "confidence": 0.7, "rationale": "a"},
        {"horizon_days": 60, "expected_low": 98, "expected_high": 122, "confidence": 0.6, "rationale": "b"},
        {"horizon_days": 90, "expected_low": 95, "expected_high": 130, "confidence": 0.5, "rationale": "c"},
        {"horizon_days": 180, "expected_low": 90, "expected_high": 145, "confidence": 0.4, "rationale": "d"},
        {"horizon_days": 360, "expected_low": 80, "expected_high": 170, "confidence": 0.3, "rationale": "e"},
    ]
}


def _seed_company(db, ticker, tier=CoverageTier.watchlist):
    company = Company(ticker=ticker, name="Router Forecast Co", coverage_tier=tier)
    db.add(company)
    db.flush()
    db.add(WikiSection(company_id=company.id, section_key=WikiSectionKey.overview, body="Overview."))
    db.commit()
    return company


def _mock_groq_client(monkeypatch, return_value):
    mock_instance = MagicMock()
    mock_instance.generate_json.return_value = return_value
    monkeypatch.setattr(forecast_service, "GroqClient", MagicMock(return_value=mock_instance))


# --- Dormant (no key) paths -- the standby's whole point (spec.md FR-33a) ---

def test_status_features_forecast_false_without_key(client, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", None)

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["features"]["forecast"] is False


def test_status_features_forecast_true_with_key(client, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")

    response = client.get("/status")

    assert response.json()["features"]["forecast"] is True


def test_forecast_without_key_returns_503_and_writes_nothing(client, db_session, monkeypatch):
    company = _seed_company(db_session, "ZFR1")
    monkeypatch.setattr(settings, "groq_api_key", None)
    jobs_before = db_session.query(JobRun).count()

    response = client.post("/companies/ZFR1/forecast")

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()
    # No provider_call_log, no job_runs, no forecast rows -- a complete non-event.
    assert db_session.query(PriceForecast).filter_by(company_id=company.id).count() == 0
    assert db_session.query(ProviderCallLog).filter_by(provider=ProviderName.groq).count() == 0
    assert db_session.query(JobRun).count() == jobs_before


def test_forecast_key_absent_checked_before_watchlist_tier(client, db_session, monkeypatch):
    """A lookup-tier ticker with no key must still get 503 (key blocker), not 400 (tier) --
    the key check comes first so the message names the real blocker (spec.md FR-33a)."""
    _seed_company(db_session, "ZFR2", tier=CoverageTier.lookup)
    monkeypatch.setattr(settings, "groq_api_key", None)

    response = client.post("/companies/ZFR2/forecast")

    assert response.status_code == 503


def test_forecasts_history_works_without_key(client, db_session, monkeypatch):
    _seed_company(db_session, "ZFR3")
    monkeypatch.setattr(settings, "groq_api_key", None)

    response = client.get("/companies/ZFR3/forecasts")

    assert response.status_code == 200
    body = response.json()
    assert body == {"ticker": "ZFR3", "latest": None, "history": []}


# --- Active (key present) paths ---

def test_forecast_rejected_for_lookup_tier_with_key(client, db_session, monkeypatch):
    _seed_company(db_session, "ZFR4", tier=CoverageTier.lookup)
    monkeypatch.setattr(settings, "groq_api_key", "test-key")

    response = client.post("/companies/ZFR4/forecast")

    assert response.status_code == 400


def test_forecast_returns_404_for_unknown_ticker_with_key(client, monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-key")

    response = client.post("/companies/ZNONE/forecast")

    assert response.status_code == 404


def test_forecast_success_for_watchlist_ticker(client, db_session, monkeypatch):
    _seed_company(db_session, "ZFR5")
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    _mock_groq_client(monkeypatch, FORECAST_JSON)

    response = client.post("/companies/ZFR5/forecast")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "ZFR5"
    assert [f["horizon_days"] for f in body["forecasts"]] == [30, 60, 90, 180, 360]
