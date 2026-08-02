import httpx

from app.providers.base import DataProvider, ProviderError

BASE_URL = "https://finnhub.io/api/v1"


class FinnhubClient(DataProvider):
    def __init__(self, api_key: str, timeout: float = 10.0):
        if not api_key:
            raise ProviderError("Finnhub API key is not configured")
        self._api_key = api_key
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def get_profile(self, ticker: str) -> dict:
        response = self._client.get(
            "/stock/profile2", params={"symbol": ticker, "token": self._api_key}
        )
        self._raise_for_status(response, ticker)
        data = response.json()
        if not data:
            raise ProviderError(
                f"Finnhub returned an empty profile for {ticker!r} -- likely an invalid ticker"
            )
        return data

    def get_quote(self, ticker: str) -> dict:
        response = self._client.get(
            "/quote", params={"symbol": ticker, "token": self._api_key}
        )
        self._raise_for_status(response, ticker)
        data = response.json()
        if data.get("c") is None:
            raise ProviderError(f"Finnhub returned no quote data for {ticker!r}")
        return data

    @staticmethod
    def _raise_for_status(response: httpx.Response, ticker: str) -> None:
        if response.status_code == 401:
            raise ProviderError("Finnhub authentication failed -- check FINNHUB_API_KEY")
        if response.status_code == 429:
            raise ProviderError("Finnhub rate limit exceeded")
        if response.is_error:
            raise ProviderError(
                f"Finnhub request failed for {ticker!r}: {response.status_code} {response.text}"
            )
