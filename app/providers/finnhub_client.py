from datetime import datetime, timedelta, timezone

import httpx

from app.providers.base import DataProvider, PermanentProviderError, TransientProviderError

BASE_URL = "https://finnhub.io/api/v1"
NEWS_LOOKBACK_DAYS = 7


class FinnhubClient(DataProvider):
    def __init__(self, api_key: str, timeout: float = 10.0):
        if not api_key:
            raise PermanentProviderError("Finnhub API key is not configured")
        self._api_key = api_key
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def get_profile(self, ticker: str) -> dict:
        data = self._get("/stock/profile2", ticker, {"symbol": ticker})
        if not data:
            raise PermanentProviderError(
                f"Finnhub returned an empty profile for {ticker!r} -- likely an invalid ticker"
            )
        return {
            "name": data.get("name"),
            "exchange": data.get("exchange"),
            "sector": data.get("finnhubIndustry"),
            "logo_url": data.get("logo"),
            "market_cap": data.get("marketCapitalization"),
        }

    def get_quote(self, ticker: str) -> dict:
        data = self._get("/quote", ticker, {"symbol": ticker})
        if data.get("c") is None:
            raise PermanentProviderError(f"Finnhub returned no quote data for {ticker!r}")
        return {
            "open": data.get("o"),
            "high": data.get("h"),
            "low": data.get("l"),
            "close": data.get("c"),
            "previous_close": data.get("pc"),
        }

    def get_news(self, ticker: str) -> list[dict]:
        # Finnhub's free tier doesn't classify sentiment -- "sentiment" stays None here, and
        # Alpha Vantage's NEWS_SENTIMENT (used as fallback) is what actually populates it when
        # available. An empty list is a normal outcome (no recent news), not an error.
        today = datetime.now(timezone.utc).date()
        since = today - timedelta(days=NEWS_LOOKBACK_DAYS)
        data = self._get(
            "/company-news",
            ticker,
            {"symbol": ticker, "from": since.isoformat(), "to": today.isoformat()},
        )
        if not isinstance(data, list):
            return []

        articles = []
        for item in data:
            headline = item.get("headline")
            url = item.get("url")
            if not headline or not url:
                continue
            published_at = None
            ts = item.get("datetime")
            if ts:
                published_at = datetime.fromtimestamp(ts, tz=timezone.utc)
            articles.append(
                {
                    "headline": headline,
                    "summary": item.get("summary") or None,
                    "source": item.get("source"),
                    "published_at": published_at,
                    "sentiment": None,
                    "url": url,
                }
            )
        return articles

    def _get(self, path: str, ticker: str, params: dict) -> dict | list:
        try:
            response = self._client.get(path, params={**params, "token": self._api_key})
        except httpx.TimeoutException as exc:
            raise TransientProviderError(f"Finnhub request timed out for {ticker!r}") from exc
        except httpx.TransportError as exc:
            raise TransientProviderError(f"Finnhub request failed for {ticker!r}: {exc}") from exc

        self._raise_for_status(response, ticker)
        return response.json()

    @staticmethod
    def _raise_for_status(response: httpx.Response, ticker: str) -> None:
        if response.status_code == 401:
            raise PermanentProviderError("Finnhub authentication failed -- check FINNHUB_API_KEY")
        if response.status_code == 429:
            raise TransientProviderError("Finnhub rate limit exceeded")
        if response.status_code >= 500:
            raise TransientProviderError(
                f"Finnhub server error for {ticker!r}: {response.status_code}"
            )
        if response.is_error:
            raise PermanentProviderError(
                f"Finnhub request failed for {ticker!r}: {response.status_code} {response.text}"
            )
