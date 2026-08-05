from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import refresh_service, ticker_directory_service

router = APIRouter(tags=["internal"])


@router.post("/internal/refresh")
def trigger_refresh(db: Session = Depends(get_db)):
    return refresh_service.refresh_watchlist(db)


@router.post("/internal/refresh-ticker-directory")
def trigger_refresh_ticker_directory(db: Session = Depends(get_db)):
    return ticker_directory_service.refresh_directory(db)
