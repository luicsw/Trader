import httpx
import pytest
import respx

from app.providers.alpha_vantage_client import AlphaVantageClient
from app.providers.base import PermanentProviderError, TransientProviderError


@respx.mock
def test_get_profile_returns_normalized_data():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "Symbol": "IBM",
                "Name": "International Business Machines",
                "Exchange": "NYSE",
                "Sector": "TECHNOLOGY",
                "MarketCapitalization": "123456789",
            },
        )
    )
    client = AlphaVantageClient(api_key="test-key")

    profile = client.get_profile("IBM")

    assert profile == {
        "name": "International Business Machines",
        "exchange": "NYSE",
        "sector": "TECHNOLOGY",
        "logo_url": None,
        "market_cap": 123456789.0,
    }


@respx.mock
def test_get_profile_empty_response_raises_permanent_error():
    respx.get("https://www.alphavantage.co/query").mock(return_value=httpx.Response(200, json={}))
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(PermanentProviderError):
        client.get_profile("BADTICKER")


@respx.mock
def test_get_profile_rate_limit_note_raises_transient_error():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(
            200, json={"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is..."}
        )
    )
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_profile("IBM")


@respx.mock
def test_get_quote_returns_normalized_data():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "Global Quote": {
                    "02. open": "129.80",
                    "03. high": "130.15",
                    "04. low": "128.90",
                    "05. price": "129.96",
                    "08. previous close": "128.90",
                }
            },
        )
    )
    client = AlphaVantageClient(api_key="test-key")

    quote = client.get_quote("IBM")

    assert quote == {
        "open": 129.80,
        "high": 130.15,
        "low": 128.90,
        "close": 129.96,
        "previous_close": 128.90,
    }


@respx.mock
def test_get_quote_missing_price_raises_permanent_error():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json={"Global Quote": {}})
    )
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(PermanentProviderError):
        client.get_quote("BADTICKER")


@respx.mock
def test_get_quote_information_note_raises_transient_error():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json={"Information": "rate limit reached"})
    )
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_quote("IBM")


@respx.mock
def test_get_quote_server_error_raises_transient_error():
    respx.get("https://www.alphavantage.co/query").mock(return_value=httpx.Response(503))
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_quote("IBM")


def test_missing_api_key_raises_permanent_error_immediately():
    with pytest.raises(PermanentProviderError):
        AlphaVantageClient(api_key="")
