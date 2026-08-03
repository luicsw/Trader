from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.providers.base import ProviderError
from app.services import watchlist_service

router = APIRouter(tags=["watchlist"])


@router.get("/watchlist")
def list_watchlist(db: Session = Depends(get_db)):
    return watchlist_service.list_watchlist(db)


@router.post("/watchlist/{ticker}/promote")
def promote(ticker: str, db: Session = Depends(get_db)):
    try:
        return watchlist_service.promote(db, ticker)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/watchlist/{ticker}")
def remove(ticker: str, db: Session = Depends(get_db)):
    watchlist_service.remove(db, ticker)
    return {"ticker": ticker.upper(), "removed": True}
