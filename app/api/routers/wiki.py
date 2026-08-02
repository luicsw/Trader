from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Company, CoverageTier, PriceBar
from app.db.session import get_db
from app.providers.base import ProviderError
from app.providers.finnhub_client import FinnhubClient

router = APIRouter(tags=["wiki"])


@router.get("/companies/{ticker}/wiki")
def get_wiki(ticker: str, db: Session = Depends(get_db)):
    # Temporary inline implementation for Phase 1 -- replaced by wiki_service.assemble()
    # in Phase 2, which will read from Postgres instead of calling the provider live.
    ticker = ticker.upper()

    if not settings.finnhub_api_key:
        raise HTTPException(status_code=503, detail="FINNHUB_API_KEY is not configured")

    client = FinnhubClient(settings.finnhub_api_key)
    try:
        profile = client.get_profile(ticker)
        quote = client.get_quote(ticker)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)

    # Upsert via ON CONFLICT so a repeated call can never duplicate or corrupt a row
    # (spec.md FR-4) -- this is the pattern refresh_service will reuse in Phase 3.
    company_fields = {
        "name": profile.get("name"),
        "exchange": profile.get("exchange"),
        "sector": profile.get("finnhubIndustry"),
        "logo_url": profile.get("logo"),
        "market_cap": profile.get("marketCapitalization"),
        "last_profile_refresh_at": now,
    }
    company_stmt = (
        pg_insert(Company)
        .values(ticker=ticker, coverage_tier=CoverageTier.lookup, **company_fields)
        .on_conflict_do_update(index_elements=[Company.ticker], set_=company_fields)
        .returning(Company.id)
    )
    company_id = db.execute(company_stmt).scalar_one()

    bar_ts = now.replace(minute=0, second=0, microsecond=0)
    bar_fields = {
        "open": quote.get("o"),
        "high": quote.get("h"),
        "low": quote.get("l"),
        "close": quote.get("c"),
    }
    bar_stmt = (
        pg_insert(PriceBar)
        .values(company_id=company_id, ts=bar_ts, interval="1d", **bar_fields)
        .on_conflict_do_update(
            index_elements=[PriceBar.company_id, PriceBar.ts, PriceBar.interval],
            set_=bar_fields,
        )
    )
    db.execute(bar_stmt)
    db.commit()

    return {
        "ticker": ticker,
        "name": profile.get("name"),
        "exchange": profile.get("exchange"),
        "sector": profile.get("finnhubIndustry"),
        "market_cap": profile.get("marketCapitalization"),
        "logo_url": profile.get("logo"),
        "last_price": quote.get("c"),
        "previous_close": quote.get("pc"),
        "day_high": quote.get("h"),
        "day_low": quote.get("l"),
        "last_updated": now.isoformat(),
    }
