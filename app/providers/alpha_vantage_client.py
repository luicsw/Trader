import httpx

from app.providers.base import DataProvider, PermanentProviderError, TransientProviderError

BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageClient(DataProvider):
    """Fallback-only provider (plan.md: "treated strictly as an emergency fallback, not a
    load-shared partner") -- its free daily cap is small, so the rate limiter budgets it
    accordingly. Alpha Vantage signals rate-limiting via a 200 response body containing a
    "Note"/"Information" field rather than an HTTP status code, so that has to be checked
    explicitly on every call.
    """

    def __init__(self, api_key: str, timeout: float = 10.0):
        if not api_key:
            raise PermanentProviderError("Alpha Vantage API key is not configured")
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout)

    def get_profile(self, ticker: str) -> dict:
        data = self._get({"function": "OVERVIEW", "symbol": ticker}, ticker)
        if not data or "Symbol" not in data:
            raise PermanentProviderError(
                f"Alpha Vantage returned an empty profile for {ticker!r} -- likely an invalid ticker"
            )
        return {
            "name": data.get("Name"),
            "exchange": data.get("Exchange"),
            "sector": data.get("Sector"),
            "logo_url": None,
            "market_cap": _to_float(data.get("MarketCapitalization")),
        }

    def get_quote(self, ticker: str) -> dict:
        data = self._get({"function": "GLOBAL_QUOTE", "symbol": ticker}, ticker)
        quote = data.get("Global Quote") or {}
        if not quote.get("05. price"):
            raise PermanentProviderError(f"Alpha Vantage returned no quote data for {ticker!r}")
        return {
            "open": _to_float(quote.get("02. open")),
            "high": _to_float(quote.get("03. high")),
            "low": _to_float(quote.get("04. low")),
            "close": _to_float(quote.get("05. price")),
            "previous_close": _to_float(quote.get("08. previous close")),
        }

    def _get(self, params: dict, ticker: str) -> dict:
        try:
            response = self._client.get(BASE_URL, params={**params, "apikey": self._api_key})
        except httpx.TimeoutException as exc:
            raise TransientProviderError(f"Alpha Vantage request timed out for {ticker!r}") from exc
        except httpx.TransportError as exc:
            raise TransientProviderError(
                f"Alpha Vantage request failed for {ticker!r}: {exc}"
            ) from exc

        if response.status_code == 429:
            raise TransientProviderError("Alpha Vantage rate limit exceeded")
        if response.status_code >= 500:
            raise TransientProviderError(
                f"Alpha Vantage server error for {ticker!r}: {response.status_code}"
            )
        if response.is_error:
            raise PermanentProviderError(
                f"Alpha Vantage request failed for {ticker!r}: {response.status_code} {response.text}"
            )

        data = response.json()
        note = data.get("Note") or data.get("Information")
        if note:
            raise TransientProviderError(
                f"Alpha Vantage rate limit/quota message for {ticker!r}: {note}"
            )
        return data


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
