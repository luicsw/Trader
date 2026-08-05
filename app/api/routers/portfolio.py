from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import portfolio_projection_service

router = APIRouter(tags=["portfolio"])


@router.get("/portfolio/projected-income")
def projected_income(
    tickers: str | None = Query(default=None),
    horizon: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Expected profit at 30/60/90-day horizons (spec.md FR-27 to FR-29). Both params are
    optional narrowing filters: `tickers` (comma-separated) restricts which holdings are
    included, `horizon` restricts the response to a single horizon. A bare call returns every
    holding at all three horizons. Pure computation -- no AI or provider call.
    """
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()] if tickers else None
    horizons = [horizon] if horizon is not None else list(portfolio_projection_service.DEFAULT_HORIZONS)
    return portfolio_projection_service.compute_projected_income(db, tickers=ticker_list, horizons=horizons)
