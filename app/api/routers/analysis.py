from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AiAnalysis, AiCritique, AnalysisTrigger, Company, CoverageTier
from app.db.session import get_db
from app.providers.base import ProviderError
from app.services import ai_service, lookup_service

router = APIRouter(tags=["analysis"])


def _serialize_analysis(analysis: AiAnalysis) -> dict:
    return {
        "id": analysis.id,
        "ticker": analysis.company.ticker,
        "verdict": analysis.verdict.value,
        "confidence": analysis.confidence,
        "reasoning": analysis.reasoning_text,
        "price_targets": analysis.price_targets,
        "hold_period_days": analysis.hold_period_days,
        "cited_sources": analysis.cited_sources,
        "trigger": analysis.trigger.value,
        "generated_at": analysis.generated_at.isoformat(),
    }


def _serialize_critique(critique: AiCritique) -> dict:
    return {
        "id": critique.id,
        "analysis_id": critique.analysis_id,
        "agrees_with_verdict_direction": critique.agrees_with_verdict_direction,
        "biggest_weakness": critique.biggest_weakness,
        "revised_price_targets": critique.revised_price_targets,
        "revised_confidence": critique.revised_confidence,
        "rationale": critique.rationale,
        "generated_at": critique.generated_at.isoformat(),
    }


@router.post("/companies/{ticker}/analyze")
def analyze(ticker: str, db: Session = Depends(get_db)):
    try:
        lookup_service.get_or_fetch(db, ticker)  # ensure the company/wiki data exists first
        analysis = ai_service.generate_verdict(db, ticker, AnalysisTrigger.on_demand)
    except ai_service.QuotaExhaustedError:
        raise HTTPException(status_code=429, detail="AI quota reached, try again later.")
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _serialize_analysis(analysis)


@router.post("/internal/analyze-scheduled")
def analyze_scheduled(db: Session = Depends(get_db)):
    return ai_service.analyze_scheduled(db)


@router.post("/companies/{ticker}/critique")
def critique(ticker: str, analysis_id: int, db: Session = Depends(get_db)):
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        raise HTTPException(status_code=404, detail=f"{ticker} not found")
    if company.coverage_tier != CoverageTier.watchlist:
        raise HTTPException(
            status_code=400,
            detail="Second-opinion critique is only available for watchlist tickers.",
        )

    try:
        result = ai_service.generate_critique(db, ticker, analysis_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ai_service.QuotaExhaustedError:
        raise HTTPException(status_code=429, detail="AI quota reached, try again later.")
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _serialize_critique(result)
