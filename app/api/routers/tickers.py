from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import ticker_directory_service

router = APIRouter(tags=["tickers"])


@router.get("/tickers/search")
def search_tickers(q: str, limit: int = 10, db: Session = Depends(get_db)):
    """Local-only ticker/name autocomplete for the Add Holding form (spec.md FR-34) -- reads
    ticker_directory only, no live provider call, so it's safe on every keystroke. Distinct
    from /companies/search, which proxies Finnhub live for deliberate discovery lookups.
    """
    return ticker_directory_service.search(db, q, limit=limit)
