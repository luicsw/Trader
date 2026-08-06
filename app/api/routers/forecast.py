from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Company, CoverageTier
from app.db.session import get_db
from app.providers import groq_client
from app.providers.base import ProviderError
from app.services import ai_service, forecast_service

router = APIRouter(tags=["forecast"])


def _serialize_forecast_row(row) -> dict:
    return {
        "id": row.id,
        "horizon_days": row.horizon_days,
        "expected_low": row.expected_low,
        "expected_high": row.expected_high,
        "confidence": row.confidence,
        "rationale": row.rationale,
        "model": row.model,
        "generated_at": row.generated_at.isoformat(),
    }


@router.post("/companies/{ticker}/forecast")
def create_forecast(ticker: str, db: Session = Depends(get_db)):
    """Generate a multi-horizon forecast (spec.md FR-30/FR-32). Watchlist-only and on-demand
    only, mirroring /critique's gating. The key-absent 503 branch is checked FIRST -- before
    the watchlist check -- so the message names the real blocker (the dormant feature) rather
    than a misleading "not on your watchlist" (spec.md FR-33a).
    """
    ticker = ticker.upper()

    # Key-absent 503 FIRST, before the watchlist check, so the message names the real blocker
    # (the dormant feature) rather than a misleading tier error (spec.md FR-33a).
    if not groq_client.is_available(settings.groq_api_key):
        raise HTTPException(status_code=503, detail="Groq API key not configured")

    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        raise HTTPException(status_code=404, detail=f"{ticker} not found")
    if company.coverage_tier != CoverageTier.watchlist:
        raise HTTPException(
            status_code=400,
            detail="Forecasts are only available for watchlist tickers.",
        )

    try:
        rows = forecast_service.generate_forecast(db, ticker)
    except forecast_service.ForecastUnavailableError as exc:
        # Defensive: generate_forecast re-checks the key (belt-and-suspenders) -- reached only
        # if the key vanished between the check above and here.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ai_service.QuotaExhaustedError:
        raise HTTPException(status_code=429, detail="AI quota reached, try again later.")
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {"ticker": ticker, "forecasts": [_serialize_forecast_row(r) for r in rows]}


@router.get("/companies/{ticker}/forecasts")
def list_forecasts(ticker: str, db: Session = Depends(get_db)):
    """Latest + historical forecast rows. Works regardless of Groq key state -- reading history
    needs no provider -- returning an empty structure when nothing has been generated (FR-33a).
    """
    return forecast_service.list_forecasts(db, ticker)
