import httpx
import pytest
import respx

from app.config import settings


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)


def _mock_finnhub_success(name="Router Co"):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NASDAQ"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 10, "o": 9, "h": 11, "l": 8, "pc": 9.5})
    )


@respx.mock
def test_get_wiki_returns_assembled_page(client):
    _mock_finnhub_success()

    response = client.get("/companies/rtr/wiki")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RTR"
    assert body["name"] == "Router Co"
    assert body["coverage_tier"] == "lookup"
    assert body["latest_price"]["close"] == 10.0
    assert set(body["sections"].keys()) == {
        "overview",
        "key_metrics",
        "financials_summary",
        "news_digest",
        "risks_notes",
    }


@respx.mock
def test_get_wiki_ticker_is_case_insensitive(client):
    _mock_finnhub_success()

    response = client.get("/companies/rtr/wiki")

    assert response.json()["ticker"] == "RTR"


@respx.mock
def test_get_wiki_returns_502_when_provider_fails(client):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={})
    )

    response = client.get("/companies/badticker/wiki")

    assert response.status_code == 502
    assert "BADTICKER" in response.json()["detail"]
