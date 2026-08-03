"""Near-live intraday price polling (Post-Phase-5 addition). Finnhub's free tier has no
intraday candle endpoint (confirmed live: /stock/candle returns an access-denied error for
this project's key), so "near-live" here means the frontend polls a lightweight endpoint
while a company page is open, and each poll's quote gets aggregated into a 5-minute
price_bars row server-side -- a real (if coarse) intraday series built from repeated /quote
calls rather than a restricted/paid endpoint.
"""
from app.db.models import Company, PriceBar
from app.services import ingest_service, provider_orchestrator


def poll_and_record(db, company: Company) -> PriceBar | None:
    """Returns None (never raises) if the quote fetch fails/is unavailable -- callers should
    surface this as "live price temporarily unavailable" rather than a hard error, since a
    missed poll is a normal, expected outcome under free-tier rate limits.
    """
    quote = provider_orchestrator.fetch_quote_best_effort(db, company.ticker)
    if quote is None or quote.get("close") is None:
        return None
    return ingest_service.record_live_quote(db, company.id, quote["close"])
