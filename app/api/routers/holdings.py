from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.providers.base import ProviderError
from app.services import holdings_service

router = APIRouter(tags=["holdings"])


class HoldingUpsert(BaseModel):
    shares: float = Field(gt=0)
    cost_basis_per_share: float = Field(gt=0)
    acquired_at: datetime | None = None
    notes: str | None = None


@router.get("/holdings")
def list_holdings(db: Session = Depends(get_db)):
    return holdings_service.list_holdings(db)


@router.post("/holdings/{ticker}")
def upsert_holding(ticker: str, body: HoldingUpsert, db: Session = Depends(get_db)):
    try:
        return holdings_service.upsert(
            db, ticker, body.shares, body.cost_basis_per_share, body.acquired_at, body.notes
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/holdings/{ticker}")
def remove_holding(ticker: str, db: Session = Depends(get_db)):
    holdings_service.remove(db, ticker)
    return {"ticker": ticker.upper(), "removed": True}
