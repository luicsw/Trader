from collections import namedtuple

import pytest

from app.services import technicals_service

Bar = namedtuple("Bar", ["close", "high", "low"])


def _bars(closes, highs=None, lows=None):
    highs = highs or closes
    lows = lows or closes
    return [Bar(close=c, high=h, low=l) for c, h, l in zip(closes, highs, lows)]


def test_compute_swing_levels_no_bars_returns_all_nulls():
    result = technicals_service.compute_swing_levels([])
    assert result == {"high_20d": None, "low_20d": None, "high_60d": None, "low_60d": None}


def test_compute_swing_levels_uses_whatever_history_exists():
    bars = _bars(closes=[10, 12, 8], highs=[11, 13, 9], lows=[9, 11, 7])

    result = technicals_service.compute_swing_levels(bars)

    assert result["high_20d"] == 13
    assert result["low_20d"] == 7
    assert result["high_60d"] == 13
    assert result["low_60d"] == 7


def test_compute_swing_levels_only_considers_first_n_bars():
    bars = _bars(closes=list(range(30)), highs=list(range(30)), lows=list(range(30)))

    result = technicals_service.compute_swing_levels(bars)

    assert result["high_20d"] == 19  # only the first 20 (index 0-19) considered
    assert result["high_60d"] == 29  # all 30 fit within the 60d window


def test_compute_price_summary_no_bars_returns_all_nulls():
    result = technicals_service.compute_price_summary([])
    assert result["last_close"] is None
    assert all(v is None for v in result.values())


def test_compute_price_summary_change_pct_needs_enough_history():
    bars = _bars(closes=[110, 100])  # only 1 bar of lookback available

    result = technicals_service.compute_price_summary(bars)

    assert result["last_close"] == 110
    assert result["change_1d_pct"] == 10.0
    assert result["change_1m_pct"] is None  # not enough history for a 21-bar lookback


def test_compute_price_summary_moving_average_needs_full_window():
    bars = _bars(closes=[100] * 49)  # one short of the 50-bar window

    result = technicals_service.compute_price_summary(bars)

    assert result["vs_50d_ma_pct"] is None


def test_compute_price_summary_moving_average_with_full_window():
    bars = _bars(closes=[110] + [100] * 49)  # 50 bars total, average = 5010/50 = 100.2

    result = technicals_service.compute_price_summary(bars)

    assert result["vs_50d_ma_pct"] == pytest.approx(9.78, abs=0.01)
