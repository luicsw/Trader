import httpx
import pytest
import respx

from app.providers.base import ProviderError
from app.providers.finnhub_client import FinnhubClient


@respx.mock
def test_get_profile_returns_parsed_data():
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(
            200, json={"name": "Apple Inc", "exchange": "NASDAQ", "ticker": "AAPL"}
        )
    )
    client = FinnhubClient(api_key="test-key")

    profile = client.get_profile("AAPL")

    assert profile["name"] == "Apple Inc"


@respx.mock
def test_get_profile_empty_response_raises():
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={})
    )
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(ProviderError):
        client.get_profile("BADTICKER")


@respx.mock
def test_get_quote_rate_limit_raises_provider_error():
    respx.get("https://finnhub.io/api/v1/quote").mock(return_value=httpx.Response(429))
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(ProviderError):
        client.get_quote("AAPL")


@respx.mock
def test_get_quote_missing_price_raises():
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": None})
    )
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(ProviderError):
        client.get_quote("BADTICKER")


def test_missing_api_key_raises_immediately():
    with pytest.raises(ProviderError):
        FinnhubClient(api_key="")
