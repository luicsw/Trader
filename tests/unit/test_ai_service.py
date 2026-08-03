from app.services import ai_service


def _wiki(**overrides) -> dict:
    base = {
        "ticker": "AAPL",
        "name": "Apple Inc",
        "sector": "Technology",
        "exchange": "NASDAQ",
        "last_updated": "2026-08-03T10:00:00+00:00",
        "market_cap": 3_000_000,
        "price_summary": {"last_close": 200.0},
        "recent_swing_levels": {"high_20d": 210.0, "low_20d": 190.0},
        "recent_news": [{"headline": "Apple news", "url": "https://example.com/a"}],
        "sections": {
            "overview": {"body": "Apple Inc overview text."},
            "risks_notes": {"body": "Some risks."},
        },
    }
    base.update(overrides)
    return base


def test_wiki_to_prompt_data_maps_full_wiki():
    data = ai_service.wiki_to_prompt_data(_wiki())

    assert data["ticker"] == "AAPL"
    assert data["company_name"] == "Apple Inc"
    assert data["overview_text"] == "Apple Inc overview text."
    assert data["risks_notes_text"] == "Some risks."
    assert data["price_summary"]["last_close"] == 200.0
    assert data["recent_swing_levels"]["high_20d"] == 210.0
    assert data["news_digest_last_6"][0]["headline"] == "Apple news"
    assert data["financials_summary_last_4_periods"] == []  # no fundamentals table yet


def test_wiki_to_prompt_data_thin_wiki_falls_back_honestly():
    thin = _wiki(name=None, sector=None, exchange=None, recent_news=[], sections={})

    data = ai_service.wiki_to_prompt_data(thin)

    assert data["company_name"] == "AAPL"  # falls back to ticker
    assert data["sector"] == "Unknown"
    assert data["exchange"] == "Unknown"
    assert data["overview_text"] == ""
    assert data["news_digest_last_6"] == []


def test_wiki_to_prompt_data_no_holding_is_honest_about_no_position():
    data = ai_service.wiki_to_prompt_data(_wiki())

    assert "No position" in data["position_text"]
    assert "AAPL" in data["position_text"]


def test_wiki_to_prompt_data_includes_holding_details():
    holding = {
        "shares": 10.0,
        "cost_basis_per_share": 150.0,
        "acquired_at": "2026-01-15T00:00:00+00:00",
        "notes": "Long-term conviction",
        "unrealized_gain_pct": 33.3,
    }
    data = ai_service.wiki_to_prompt_data(_wiki(holding=holding))

    assert "10.0 shares" in data["position_text"]
    assert "$150.00/share" in data["position_text"]
    assert "+33.3%" in data["position_text"]
    assert "Long-term conviction" in data["position_text"]
