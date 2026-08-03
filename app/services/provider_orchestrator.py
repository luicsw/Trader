"""fetch_with_fallback(ticker) -- tries Finnhub first, falls back to Alpha Vantage on
failure/rate-limit/open-circuit (spec.md FR-1). Lives in services/, not providers/, because
it depends on the DB-backed rate limiter and circuit breaker; providers/ stays pure API
clients with no DB dependency.

Every call attempt is logged to provider_call_log (audit trail + what seeds the rate
limiter/circuit breaker). Transient errors are retried with jittered exponential backoff
before falling back to the other provider (FR-2); permanent errors skip retry and fall back
immediately (FR-3).
"""
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from app.config import settings
from app.db.models import CallStatus, ProviderName
from app.providers.alpha_vantage_client import AlphaVantageClient
from app.providers.base import DataProvider, PermanentProviderError, ProviderError, TransientProviderError
from app.providers.finnhub_client import FinnhubClient
from app.services import circuit_breaker, rate_limiter


def fetch_with_fallback(db, ticker: str) -> dict:
    """Returns {"provider": ProviderName, "profile": {...}, "quote": {...}}."""
    providers = _configured_providers()
    if not providers:
        raise PermanentProviderError("No data providers are configured (FINNHUB_API_KEY/ALPHA_VANTAGE_API_KEY)")

    errors = []
    for name, client in providers:
        if not circuit_breaker.is_available(db, name):
            errors.append(f"{name.value}: circuit open")
            continue
        if not rate_limiter.allow(db, name):
            errors.append(f"{name.value}: rate limit budget exhausted")
            continue

        try:
            profile = _call_with_retry(db, name, client.get_profile, ticker)
            quote = _call_with_retry(db, name, client.get_quote, ticker)
        except ProviderError as exc:
            errors.append(f"{name.value}: {exc}")
            continue

        return {"provider": name, "profile": profile, "quote": quote}

    raise PermanentProviderError(
        f"All providers failed or unavailable for {ticker!r}: " + "; ".join(errors)
    )


def fetch_news_best_effort(db, ticker: str) -> list[dict]:
    """Best-effort news fetch: tries each configured provider once, respecting the same
    rate limits/circuit breakers and logging every attempt to provider_call_log, but NEVER
    raises -- news is a supplementary signal, not the core pipeline, so a failure here must
    never block or fail the primary profile/quote refresh. No retry (unlike
    fetch_with_fallback) since this is explicitly a best-effort secondary fetch. Returns []
    if every provider is unavailable or fails.

    Deliberately catches Exception, not just ProviderError -- this is the one place in the
    app where an unexpected exception (a provider bug, a malformed response) should still
    never propagate, since news is strictly a nice-to-have signal, never worth failing a
    refresh cycle over.
    """
    for name, client in _configured_providers():
        if not circuit_breaker.is_available(db, name):
            continue
        if not rate_limiter.allow(db, name):
            continue

        try:
            articles = client.get_news(ticker)
        except Exception:
            rate_limiter.record_call(db, name, CallStatus.failure)
            db.commit()
            continue

        rate_limiter.record_call(db, name, CallStatus.success)
        db.commit()
        return articles

    return []


def backfill_price_history(db, ticker: str) -> list[dict] | None:
    """One-time historical backfill via Alpha Vantage's TIME_SERIES_DAILY (compact, ~100
    trading days -- outputsize=full is premium-gated, confirmed live). Has no fallback
    partner: Finnhub doesn't offer historical daily bars on its free tier, so this only ever
    calls Alpha Vantage directly rather than iterating `_configured_providers()`.

    Best-effort like fetch_news_best_effort: backfill is enrichment, never a hard requirement
    for watchlist promote() to succeed, so this never raises. Returns None if Alpha Vantage
    isn't configured, is unavailable (circuit open/rate limited), or the fetch fails; returns
    [] only if Alpha Vantage genuinely has no history for the ticker.
    """
    if not settings.alpha_vantage_api_key:
        return None

    name = ProviderName.alpha_vantage
    if not circuit_breaker.is_available(db, name):
        return None
    if not rate_limiter.allow(db, name):
        return None

    client = AlphaVantageClient(settings.alpha_vantage_api_key)
    try:
        bars = client.get_daily_history(ticker)
    except Exception:
        rate_limiter.record_call(db, name, CallStatus.failure)
        db.commit()
        return None

    rate_limiter.record_call(db, name, CallStatus.success)
    db.commit()
    return bars


def fetch_quote_best_effort(db, ticker: str) -> dict | None:
    """Quote-only fetch for the near-live intraday price poll (Post-Phase-5 addition) --
    Finnhub's free tier has no intraday candle endpoint (confirmed live: /stock/candle
    returns a 403-shaped access error), so the frontend polls this while a company page is
    open and the result is aggregated into 5-minute price_bars server-side
    (ingest_service.record_live_quote). Best-effort like fetch_news_best_effort: never
    raises, returns None if unconfigured/unavailable/failed -- a missed poll is just one gap
    in the live line, never a broken page.
    """
    if not settings.finnhub_api_key:
        return None

    name = ProviderName.finnhub
    if not circuit_breaker.is_available(db, name):
        return None
    if not rate_limiter.allow(db, name):
        return None

    client = FinnhubClient(settings.finnhub_api_key)
    try:
        quote = client.get_quote(ticker)
    except Exception:
        rate_limiter.record_call(db, name, CallStatus.failure)
        db.commit()
        return None

    rate_limiter.record_call(db, name, CallStatus.success)
    db.commit()
    return quote


def search_symbols_best_effort(db, query: str) -> list[dict]:
    """Ticker/name search (spec.md FR-8/§7) -- Finnhub only, no Alpha Vantage fallback (its
    equivalent SYMBOL_SEARCH isn't worth spending the scarce fallback-only daily budget on a
    nice-to-have discovery feature). Best-effort like fetch_news_best_effort/
    backfill_price_history: never raises, returns [] if unconfigured/unavailable/empty.
    """
    if not settings.finnhub_api_key:
        return []

    name = ProviderName.finnhub
    if not circuit_breaker.is_available(db, name):
        return []
    if not rate_limiter.allow(db, name):
        return []

    client = FinnhubClient(settings.finnhub_api_key)
    try:
        results = client.search_symbols(query)
    except Exception:
        rate_limiter.record_call(db, name, CallStatus.failure)
        db.commit()
        return []

    rate_limiter.record_call(db, name, CallStatus.success)
    db.commit()
    return results


def _configured_providers() -> list[tuple[ProviderName, DataProvider]]:
    providers: list[tuple[ProviderName, DataProvider]] = []
    if settings.finnhub_api_key:
        providers.append((ProviderName.finnhub, FinnhubClient(settings.finnhub_api_key)))
    if settings.alpha_vantage_api_key:
        providers.append((ProviderName.alpha_vantage, AlphaVantageClient(settings.alpha_vantage_api_key)))
    return providers


def _call_with_retry(db, provider_name: ProviderName, fn, ticker: str):
    retryer = Retrying(
        retry=retry_if_exception_type(TransientProviderError),
        stop=stop_after_attempt(3),
        wait=wait_random_exponential(multiplier=0.5, max=5),
        reraise=True,
    )
    return retryer(_logged_call, db, provider_name, fn, ticker)


def _logged_call(db, provider_name: ProviderName, fn, ticker: str):
    try:
        result = fn(ticker)
    except ProviderError:
        rate_limiter.record_call(db, provider_name, CallStatus.failure)
        db.commit()
        raise
    rate_limiter.record_call(db, provider_name, CallStatus.success)
    db.commit()
    return result
