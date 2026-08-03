import httpx
import pytest
import respx

from app.config import settings


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")


@respx.mock
def test_search_returns_normalized_results(client):
    respx.get("https://finnhub.io/api/v1/search").mock(
        return_value=httpx.Response(
            200, json={"result": [{"description": "Apple Inc", "symbol": "AAPL", "type": "Common Stock"}]}
        )
    )

    response = client.get("/companies/search?q=apple")

    assert response.status_code == 200
    assert response.json() == [{"symbol": "AAPL", "name": "Apple Inc", "type": "Common Stock"}]


def test_search_blank_query_returns_empty_without_calling_provider(client):
    response = client.get("/companies/search?q=   ")

    assert response.status_code == 200
    assert response.json() == []
