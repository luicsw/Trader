from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.providers.base import ProviderError
from app.services import lookup_service

router = APIRouter(tags=["wiki"])


@router.get("/companies/{ticker}/wiki")
def get_wiki(ticker: str, db: Session = Depends(get_db)):
    try:
        return lookup_service.get_or_fetch(db, ticker)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
