import httpx
import pytest
import respx

from app.providers.base import PermanentProviderError, TransientProviderError
from app.providers.finnhub_client import FinnhubClient


@respx.mock
def test_get_profile_returns_normalized_data():
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Apple Inc",
                "exchange": "NASDAQ",
                "finnhubIndustry": "Technology",
                "logo": "https://example.com/logo.png",
                "marketCapitalization": 3000,
            },
        )
    )
    client = FinnhubClient(api_key="test-key")

    profile = client.get_profile("AAPL")

    assert profile == {
        "name": "Apple Inc",
        "exchange": "NASDAQ",
        "sector": "Technology",
        "logo_url": "https://example.com/logo.png",
        "market_cap": 3000,
    }


@respx.mock
def test_get_profile_empty_response_raises_permanent_error():
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={})
    )
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(PermanentProviderError):
        client.get_profile("BADTICKER")


@respx.mock
def test_get_profile_auth_failure_raises_permanent_error():
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(return_value=httpx.Response(401))
    client = FinnhubClient(api_key="bad-key")

    with pytest.raises(PermanentProviderError):
        client.get_profile("AAPL")


@respx.mock
def test_get_quote_returns_normalized_data():
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"o": 9, "h": 11, "l": 8, "c": 10, "pc": 9.5})
    )
    client = FinnhubClient(api_key="test-key")

    quote = client.get_quote("AAPL")

    assert quote == {"open": 9, "high": 11, "low": 8, "close": 10, "previous_close": 9.5}


@respx.mock
def test_get_quote_rate_limit_raises_transient_error():
    respx.get("https://finnhub.io/api/v1/quote").mock(return_value=httpx.Response(429))
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_quote("AAPL")


@respx.mock
def test_get_quote_server_error_raises_transient_error():
    respx.get("https://finnhub.io/api/v1/quote").mock(return_value=httpx.Response(503))
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_quote("AAPL")


@respx.mock
def test_get_quote_timeout_raises_transient_error():
    respx.get("https://finnhub.io/api/v1/quote").mock(side_effect=httpx.TimeoutException("boom"))
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_quote("AAPL")


@respx.mock
def test_get_quote_missing_price_raises_permanent_error():
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": None})
    )
    client = FinnhubClient(api_key="test-key")

    with pytest.raises(PermanentProviderError):
        client.get_quote("BADTICKER")


def test_missing_api_key_raises_permanent_error_immediately():
    with pytest.raises(PermanentProviderError):
        FinnhubClient(api_key="")


@respx.mock
def test_get_news_returns_normalized_articles():
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "headline": "Apple announces new product",
                    "summary": "Details inside",
                    "source": "Reuters",
                    "datetime": 1735689600,
                    "url": "https://example.com/apple-news",
                },
                {"headline": "", "url": "https://example.com/missing-headline"},
            ],
        )
    )
    client = FinnhubClient(api_key="test-key")

    articles = client.get_news("AAPL")

    assert len(articles) == 1
    assert articles[0]["headline"] == "Apple announces new product"
    assert articles[0]["sentiment"] is None  # Finnhub free tier doesn't classify sentiment
    assert articles[0]["published_at"].year == 2025


@respx.mock
def test_get_news_empty_list_is_not_an_error():
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = FinnhubClient(api_key="test-key")

    assert client.get_news("AAPL") == []


@respx.mock
def test_search_symbols_returns_normalized_results():
    respx.get("https://finnhub.io/api/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 2,
                "result": [
                    {"description": "Apple Inc", "displaySymbol": "AAPL", "symbol": "AAPL", "type": "Common Stock"},
                    {"description": "", "displaySymbol": "", "symbol": "", "type": "Common Stock"},
                ],
            },
        )
    )
    client = FinnhubClient(api_key="test-key")

    results = client.search_symbols("apple")

    assert results == [{"symbol": "AAPL", "name": "Apple Inc", "type": "Common Stock"}]


@respx.mock
def test_search_symbols_no_matches_is_not_an_error():
    respx.get("https://finnhub.io/api/v1/search").mock(return_value=httpx.Response(200, json={"count": 0, "result": []}))
    client = FinnhubClient(api_key="test-key")

    assert client.search_symbols("zzzznomatch") == []
