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


@respx.mock
def test_get_news_returns_normalized_articles_with_real_sentiment():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "feed": [
                    {
                        "title": "IBM beats earnings estimates",
                        "summary": "Strong quarter",
                        "source": "Bloomberg",
                        "time_published": "20250101T093000",
                        "overall_sentiment_label": "Somewhat-Bullish",
                        "url": "https://example.com/ibm-earnings",
                    },
                    {"title": "", "url": "https://example.com/missing-title"},
                ]
            },
        )
    )
    client = AlphaVantageClient(api_key="test-key")

    articles = client.get_news("IBM")

    assert len(articles) == 1
    assert articles[0]["headline"] == "IBM beats earnings estimates"
    assert articles[0]["sentiment"] == "positive"
    assert articles[0]["published_at"].year == 2025


@respx.mock
def test_get_news_empty_feed_is_not_an_error():
    respx.get("https://www.alphavantage.co/query").mock(return_value=httpx.Response(200, json={}))
    client = AlphaVantageClient(api_key="test-key")

    assert client.get_news("IBM") == []


@respx.mock
def test_get_news_rate_limit_note_raises_transient_error():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json={"Note": "rate limited"})
    )
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_news("IBM")


@respx.mock
def test_get_daily_history_returns_normalized_bars_oldest_first():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "Meta Data": {"2. Symbol": "IBM"},
                "Time Series (Daily)": {
                    "2026-08-03": {
                        "1. open": "221.15",
                        "2. high": "224.76",
                        "3. low": "216.585",
                        "4. close": "223.65",
                        "5. volume": "9093613",
                    },
                    "2026-08-01": {
                        "1. open": "222.00",
                        "2. high": "224.86",
                        "3. low": "220.20",
                        "4. close": "221.74",
                        "5. volume": "9675157",
                    },
                },
            },
        )
    )
    client = AlphaVantageClient(api_key="test-key")

    bars = client.get_daily_history("IBM")

    assert len(bars) == 2
    assert bars[0]["ts"] < bars[1]["ts"]  # oldest first
    assert bars[-1]["close"] == 223.65
    assert bars[-1]["volume"] == 9093613


@respx.mock
def test_get_daily_history_empty_series_raises_permanent_error():
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(200, json={"Time Series (Daily)": {}})
    )
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(PermanentProviderError):
        client.get_daily_history("BADTICKER")


@respx.mock
def test_get_daily_history_outputsize_full_premium_message_raises_transient_error():
    # Real free-tier response confirmed live: outputsize=full is premium-gated and returns a
    # 200 with an "Information" upsell message instead of data.
    respx.get("https://www.alphavantage.co/query").mock(
        return_value=httpx.Response(
            200,
            json={
                "Information": (
                    "Thank you for using Alpha Vantage! The outputsize=full parameter value "
                    "is a premium feature for the TIME_SERIES_DAILY endpoint."
                )
            },
        )
    )
    client = AlphaVantageClient(api_key="test-key")

    with pytest.raises(TransientProviderError):
        client.get_daily_history("IBM")
