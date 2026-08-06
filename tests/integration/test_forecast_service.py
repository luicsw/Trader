from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.db.models import (
    CallStatus,
    Company,
    CoverageTier,
    JobRun,
    PriceForecast,
    ProviderCallLog,
    ProviderName,
    WikiSection,
    WikiSectionKey,
)
from app.providers.base import PermanentProviderError
from app.services import ai_service, forecast_service

# A recorded/hand-written Groq response fixture -- the shape json_object mode is expected to
# return (spec.md: mocked, like every other provider's parser tests, since no live key exists).
FORECAST_JSON = {
    "forecasts": [
        {"horizon_days": 30, "expected_low": 100, "expected_high": 115, "confidence": 0.7, "rationale": "recent range"},
        {"horizon_days": 60, "expected_low": 98, "expected_high": 122, "confidence": 0.6, "rationale": "trend"},
        {"horizon_days": 90, "expected_low": 95, "expected_high": 130, "confidence": 0.5, "rationale": "widening"},
        {"horizon_days": 180, "expected_low": 90, "expected_high": 145, "confidence": 0.4, "rationale": "fundamentals"},
        {"horizon_days": 360, "expected_low": 80, "expected_high": 170, "confidence": 0.3, "rationale": "long horizon"},
    ]
}


def _seed_company(db, ticker="ZFOR", tier=CoverageTier.watchlist):
    company = Company(ticker=ticker, name="Forecast Co", coverage_tier=tier)
    db.add(company)
    db.flush()
    db.add(WikiSection(company_id=company.id, section_key=WikiSectionKey.overview, body="Overview."))
    db.commit()
    return company


def _mock_groq_client(monkeypatch, return_value=None, side_effect=None):
    mock_instance = MagicMock()
    if side_effect is not None:
        mock_instance.generate_json.side_effect = side_effect
    else:
        mock_instance.generate_json.return_value = return_value
    monkeypatch.setattr(forecast_service, "GroqClient", MagicMock(return_value=mock_instance))
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    return mock_instance


def test_generate_forecast_persists_five_rows(db_session, monkeypatch):
    company = _seed_company(db_session)
    _mock_groq_client(monkeypatch, return_value=FORECAST_JSON)

    rows = forecast_service.generate_forecast(db_session, "ZFOR")

    assert [r.horizon_days for r in rows] == [30, 60, 90, 180, 360]
    stored = db_session.query(PriceForecast).filter_by(company_id=company.id).all()
    assert len(stored) == 5
    assert all(r.model == settings.groq_model for r in stored)
    assert all(r.trigger == "on_demand" for r in stored)


def test_generate_forecast_records_success_in_provider_call_log(db_session, monkeypatch):
    _seed_company(db_session)
    _mock_groq_client(monkeypatch, return_value=FORECAST_JSON)

    forecast_service.generate_forecast(db_session, "ZFOR")

    log = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.groq).one()
    assert log.status == CallStatus.success


def test_generate_forecast_dormant_without_key_is_a_non_event(db_session, monkeypatch):
    """The whole point of the standby: a missing key writes NO provider_call_log and NO
    job_runs row, touches no client, and raises a distinct ForecastUnavailableError (FR-33a)."""
    company = _seed_company(db_session)
    monkeypatch.setattr(settings, "groq_api_key", None)
    jobs_before = db_session.query(JobRun).count()

    with pytest.raises(forecast_service.ForecastUnavailableError):
        forecast_service.generate_forecast(db_session, "ZFOR")

    assert db_session.query(PriceForecast).filter_by(company_id=company.id).count() == 0
    assert db_session.query(ProviderCallLog).filter_by(provider=ProviderName.groq).count() == 0
    assert db_session.query(JobRun).count() == jobs_before  # no job_runs row written


def test_generate_forecast_provider_error_propagates_and_logs_failure(db_session, monkeypatch):
    company = _seed_company(db_session)
    _mock_groq_client(monkeypatch, side_effect=PermanentProviderError("bad shape"))

    with pytest.raises(PermanentProviderError):
        forecast_service.generate_forecast(db_session, "ZFOR")

    assert db_session.query(PriceForecast).filter_by(company_id=company.id).count() == 0
    log = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.groq).one()
    assert log.status == CallStatus.failure


def test_generate_forecast_quota_exhausted_before_any_call(db_session, monkeypatch):
    _seed_company(db_session)
    monkeypatch.setattr(settings, "groq_api_key", "test-key")
    limit = settings.groq_rate_limit_per_window
    now = datetime.now(timezone.utc)
    for _ in range(limit):
        db_session.add(ProviderCallLog(provider=ProviderName.groq, status=CallStatus.success, called_at=now))
    db_session.commit()

    with pytest.raises(ai_service.QuotaExhaustedError):
        forecast_service.generate_forecast(db_session, "ZFOR")


def test_parse_forecasts_rejects_missing_horizon(db_session, monkeypatch):
    _seed_company(db_session)
    incomplete = {"forecasts": FORECAST_JSON["forecasts"][:3]}  # only 30/60/90
    _mock_groq_client(monkeypatch, return_value=incomplete)

    with pytest.raises(PermanentProviderError):
        forecast_service.generate_forecast(db_session, "ZFOR")


def test_parse_forecasts_rejects_high_below_low(db_session, monkeypatch):
    _seed_company(db_session)
    bad = {"forecasts": [dict(f) for f in FORECAST_JSON["forecasts"]]}
    bad["forecasts"][0]["expected_high"] = 50  # < expected_low 100
    _mock_groq_client(monkeypatch, return_value=bad)

    with pytest.raises(PermanentProviderError):
        forecast_service.generate_forecast(db_session, "ZFOR")


def test_list_forecasts_empty_for_unknown_ticker(db_session):
    result = forecast_service.list_forecasts(db_session, "ZNOPE")

    assert result == {"ticker": "ZNOPE", "latest": None, "history": []}


def test_list_forecasts_groups_by_generation(db_session, monkeypatch):
    _seed_company(db_session)
    _mock_groq_client(monkeypatch, return_value=FORECAST_JSON)
    forecast_service.generate_forecast(db_session, "ZFOR")

    result = forecast_service.list_forecasts(db_session, "ZFOR")

    assert result["ticker"] == "ZFOR"
    assert result["latest"] is not None
    assert [f["horizon_days"] for f in result["latest"]["forecasts"]] == [30, 60, 90, 180, 360]
    assert len(result["history"]) == 1
