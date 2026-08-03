from app.config import settings
from app.db.models import Verdict
from app.services import outcome_service


def test_buy_is_correct_when_price_rose():
    assert outcome_service._is_directionally_correct(Verdict.buy, 5.0) is True


def test_buy_is_incorrect_when_price_fell():
    assert outcome_service._is_directionally_correct(Verdict.buy, -5.0) is False


def test_sell_is_correct_when_price_fell():
    assert outcome_service._is_directionally_correct(Verdict.sell, -5.0) is True


def test_sell_is_incorrect_when_price_rose():
    assert outcome_service._is_directionally_correct(Verdict.sell, 5.0) is False


def test_hold_is_correct_within_band():
    assert outcome_service._is_directionally_correct(Verdict.hold, settings.verdict_outcome_hold_band_pct) is True
    assert outcome_service._is_directionally_correct(Verdict.hold, -settings.verdict_outcome_hold_band_pct) is True


def test_hold_is_incorrect_outside_band():
    assert outcome_service._is_directionally_correct(Verdict.hold, settings.verdict_outcome_hold_band_pct + 1) is False


def test_extract_price_at_verdict_from_context_snapshot():
    class _FakeAnalysis:
        context_snapshot = {"prompt_data": {"price_summary": {"last_close": 123.45}}}

    assert outcome_service._extract_price_at_verdict(_FakeAnalysis()) == 123.45


def test_extract_price_at_verdict_missing_returns_none():
    class _FakeAnalysis:
        context_snapshot = {"prompt_data": {"price_summary": {}}}

    assert outcome_service._extract_price_at_verdict(_FakeAnalysis()) is None
