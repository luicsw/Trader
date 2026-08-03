from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.models import AiAnalysis, VerdictOutcome
from app.db.session import get_db
from app.services import outcome_service

router = APIRouter(tags=["outcomes"])

# Postgres won't cast boolean -> double precision directly (unlike some other databases),
# so this maps directionally_correct to 1.0/0.0 explicitly before averaging into a percentage.
_CORRECT_AS_FLOAT = case((VerdictOutcome.directionally_correct, 1.0), else_=0.0)


@router.post("/internal/evaluate-outcomes")
def evaluate_outcomes(db: Session = Depends(get_db)):
    return outcome_service.evaluate_pending_outcomes(db)


@router.get("/verdicts/track-record")
def track_record(db: Session = Depends(get_db)):
    """Checks whether verdicts (and confidence) are actually calibrated against what price
    did afterward, at the fixed evaluation horizon -- not just whether the AI *sounded* sure.
    """
    by_verdict = db.execute(
        select(
            AiAnalysis.verdict,
            func.count(VerdictOutcome.id),
            func.avg(VerdictOutcome.price_change_pct),
            func.avg(_CORRECT_AS_FLOAT),
        )
        .join(VerdictOutcome, VerdictOutcome.analysis_id == AiAnalysis.id)
        .group_by(AiAnalysis.verdict)
    ).all()

    by_confidence_bucket = db.execute(
        select(
            (AiAnalysis.confidence >= 0.6).label("high_confidence"),
            func.count(VerdictOutcome.id),
            func.avg(_CORRECT_AS_FLOAT),
        )
        .join(VerdictOutcome, VerdictOutcome.analysis_id == AiAnalysis.id)
        .group_by("high_confidence")
    ).all()

    return {
        "by_verdict": [
            {
                "verdict": verdict.value,
                "count": count,
                "avg_price_change_pct": round(avg_change, 2) if avg_change is not None else None,
                "pct_directionally_correct": round(avg_correct * 100, 1) if avg_correct is not None else None,
            }
            for verdict, count, avg_change, avg_correct in by_verdict
        ],
        "by_confidence": [
            {
                "bucket": "high (>=0.6)" if high_confidence else "low (<0.6)",
                "count": count,
                "pct_directionally_correct": round(avg_correct * 100, 1) if avg_correct is not None else None,
            }
            for high_confidence, count, avg_correct in by_confidence_bucket
        ],
    }
