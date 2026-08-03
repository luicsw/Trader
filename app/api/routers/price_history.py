from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, PriceBar
from app.db.session import get_db
from app.services import ingest_service, live_price_service

router = APIRouter(tags=["price-history"])


def _serialize_bar(bar: PriceBar) -> dict:
    return {
        "ts": bar.ts.isoformat(),
        "open": float(bar.open) if bar.open is not None else None,
        "high": float(bar.high) if bar.high is not None else None,
        "low": float(bar.low) if bar.low is not None else None,
        "close": float(bar.close) if bar.close is not None else None,
    }


@router.get("/companies/{ticker}/price-history")
def get_price_history(
    ticker: str,
    interval: str = Query("1d"),
    limit: int = Query(180, le=500),
    db: Session = Depends(get_db),
):
    """Historical bars for chart context -- read-only, no provider calls (spec.md's existing
    refresh/backfill flows are what actually populate price_bars).
    """
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        return []
    bars = ingest_service.bars_for_interval(db, company.id, interval, limit)
    return [_serialize_bar(bar) for bar in bars]


@router.post("/companies/{ticker}/live-quote")
def poll_live_quote(ticker: str, db: Session = Depends(get_db)):
    """One near-live price poll (Post-Phase-5 addition) -- called by the frontend every
    ~15-30s while a company page is open, not by a background scheduler, so the free-tier
    quote budget only gets spent while someone is actually watching.
    """
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        raise HTTPException(status_code=404, detail=f"{ticker} not found")

    bar = live_price_service.poll_and_record(db, company)
    if bar is None:
        raise HTTPException(status_code=503, detail="Live quote temporarily unavailable")
    return _serialize_bar(bar)
