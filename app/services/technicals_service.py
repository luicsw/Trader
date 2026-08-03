"""Pure functions computing swing levels and price-change technicals from whatever
`price_bars` history actually exists -- no new provider calls needed, since this is derived
entirely from data already collected during refresh/lookup. Same honest-degradation
philosophy as wiki_sections_service: fewer bars than a window needs means an honest null,
never a fabricated number from insufficient history.

Bars are expected ordered most-recent-first (as ingest_service.recent_bars returns them).
Trading-day-count approximations (21/63/252 for 1mo/3mo/1yr) are standard equity conventions,
not exact calendar lookups -- fine for heuristic synthesis, not technical-analysis precision
(same caveat verdict_prompt_v1.md already documents about this whole prompt).
"""

_MONTH_TRADING_DAYS = 21
_QUARTER_TRADING_DAYS = 63
_YEAR_TRADING_DAYS = 252


def compute_swing_levels(bars_desc: list) -> dict:
    def _high_low(n: int):
        window = [b for b in bars_desc[:n] if b.high is not None and b.low is not None]
        if not window:
            return None, None
        return max(float(b.high) for b in window), min(float(b.low) for b in window)

    high_20d, low_20d = _high_low(20)
    high_60d, low_60d = _high_low(60)
    return {
        "high_20d": high_20d,
        "low_20d": low_20d,
        "high_60d": high_60d,
        "low_60d": low_60d,
    }


def compute_price_summary(bars_desc: list) -> dict:
    empty = {
        "last_close": None,
        "change_1d_pct": None,
        "change_1m_pct": None,
        "change_3m_pct": None,
        "change_1y_pct": None,
        "vs_50d_ma_pct": None,
        "vs_200d_ma_pct": None,
    }
    if not bars_desc or bars_desc[0].close is None:
        return empty

    last_close = float(bars_desc[0].close)

    def _change_pct(bars_ago: int):
        if bars_ago >= len(bars_desc) or bars_desc[bars_ago].close is None:
            return None
        past = float(bars_desc[bars_ago].close)
        return round((last_close - past) / past * 100, 2) if past else None

    def _vs_moving_average(window_size: int):
        window = [float(b.close) for b in bars_desc[:window_size] if b.close is not None]
        if len(window) < window_size:
            return None  # not enough history yet for an honest average over this window
        average = sum(window) / len(window)
        return round((last_close - average) / average * 100, 2) if average else None

    return {
        "last_close": last_close,
        "change_1d_pct": _change_pct(1),
        "change_1m_pct": _change_pct(_MONTH_TRADING_DAYS),
        "change_3m_pct": _change_pct(_QUARTER_TRADING_DAYS),
        "change_1y_pct": _change_pct(_YEAR_TRADING_DAYS),
        "vs_50d_ma_pct": _vs_moving_average(50),
        "vs_200d_ma_pct": _vs_moving_average(200),
    }
