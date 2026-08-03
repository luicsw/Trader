from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import refresh_service

router = APIRouter(tags=["internal"])


@router.post("/internal/refresh")
def trigger_refresh(db: Session = Depends(get_db)):
    return refresh_service.refresh_watchlist(db)
