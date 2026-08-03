import pytest

from app.db.models import Company, CoverageTier, WikiSection, WikiSectionKey
from app.services import ai_service


def _seed_company(db):
    company = Company(
        ticker="ZAIP",
        name="Apple Inc",
        exchange="NASDAQ",
        sector="Technology",
        market_cap=3_000_000,
        coverage_tier=CoverageTier.watchlist,
    )
    db.add(company)
    db.flush()
    db.add(WikiSection(company_id=company.id, section_key=WikiSectionKey.overview, body="Apple overview."))
    db.add(WikiSection(company_id=company.id, section_key=WikiSectionKey.risks_notes, body="Some risks."))
    db.commit()
    return company


def test_build_prompt_leaves_no_unfilled_placeholders(db_session):
    _seed_company(db_session)

    result = ai_service.build_prompt(db_session, "zaip")

    assert "{{" not in result["prompt_text"]
    assert "ZAIP" in result["prompt_text"]
    assert "Apple overview." in result["prompt_text"]
    assert result["context_snapshot"]["prompt_version"] == "verdict_prompt_v1"
    assert result["response_schema"] == ai_service.RESPONSE_SCHEMA


def test_build_prompt_raises_for_unknown_ticker(db_session):
    with pytest.raises(ValueError):
        ai_service.build_prompt(db_session, "NOPE")


def test_build_critique_prompt_includes_original_verdict(db_session):
    _seed_company(db_session)
    original_verdict = {"verdict": "hold", "confidence": 0.4, "reasoning": "thin data"}

    result = ai_service.build_critique_prompt(db_session, "zaip", original_verdict)

    assert "{{" not in result["prompt_text"]
    assert '"verdict": "hold"' in result["prompt_text"]
    assert result["context_snapshot"]["original_verdict"] == original_verdict
    assert result["response_schema"] == ai_service.CRITIQUE_RESPONSE_SCHEMA


def test_build_critique_prompt_raises_for_unknown_ticker(db_session):
    with pytest.raises(ValueError):
        ai_service.build_critique_prompt(db_session, "NOPE", {"verdict": "hold"})
