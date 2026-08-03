"""outcome_service.evaluate_pending_outcomes(db) -- checks whether a verdict's implied
direction actually matched what price did afterward, at a fixed horizon
(settings.verdict_outcome_horizon_days). Turns "the AI feels confident" into something
checkable rather than trusting its self-reported confidence score at face value.

Append-only (verdict_outcomes, same philosophy as ai_analyses/ai_critiques): never fails the
whole batch on one bad lookup, and an analysis with no horizon price data yet is skipped, not
failed -- it'll be picked up on a later run once more price history has accumulated.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.db.models import AiAnalysis, JobRun, JobStatus, PriceBar, Verdict, VerdictOutcome


def evaluate_pending_outcomes(db) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.verdict_outcome_horizon_days)
    already_evaluated = select(VerdictOutcome.analysis_id)

    candidates = db.scalars(
        select(AiAnalysis)
        .where(AiAnalysis.generated_at <= cutoff)
        .where(AiAnalysis.id.not_in(already_evaluated))
    ).all()

    evaluated, skipped = [], []
    for analysis in candidates:
        outcome = _evaluate_one(db, analysis)
        (evaluated if outcome is not None else skipped).append(analysis.id)

    db.add(
        JobRun(
            job_name="evaluate_outcomes",
            status=JobStatus.success,
            error_message=f"evaluated={len(evaluated)} skipped={len(skipped)}" if skipped else None,
        )
    )
    db.commit()
    return {"checked": len(candidates), "evaluated": evaluated, "skipped": skipped}


def _evaluate_one(db, analysis: AiAnalysis) -> VerdictOutcome | None:
    price_at_verdict = _extract_price_at_verdict(analysis)
    if price_at_verdict is None:
        return None  # no snapshotted price to compare against -- can't evaluate, skip

    horizon_ts = analysis.generated_at + timedelta(days=settings.verdict_outcome_horizon_days)
    bar = db.scalar(
        select(PriceBar)
        .where(PriceBar.company_id == analysis.company_id, PriceBar.ts >= horizon_ts)
        .order_by(PriceBar.ts.asc())
        .limit(1)
    )
    if bar is None or bar.close is None:
        return None  # not enough price history collected yet at the horizon -- retry later

    price_at_horizon = float(bar.close)
    price_change_pct = (
        (price_at_horizon - price_at_verdict) / price_at_verdict * 100 if price_at_verdict else 0.0
    )

    outcome = VerdictOutcome(
        analysis_id=analysis.id,
        horizon_days=settings.verdict_outcome_horizon_days,
        price_at_verdict=price_at_verdict,
        price_at_horizon=price_at_horizon,
        price_change_pct=price_change_pct,
        directionally_correct=_is_directionally_correct(analysis.verdict, price_change_pct),
    )
    db.add(outcome)
    db.commit()
    return outcome


def _extract_price_at_verdict(analysis: AiAnalysis) -> float | None:
    try:
        return analysis.context_snapshot["prompt_data"]["price_summary"]["last_close"]
    except (KeyError, TypeError):
        return None


def _is_directionally_correct(verdict: Verdict, price_change_pct: float) -> bool:
    if verdict == Verdict.buy:
        return price_change_pct > 0
    if verdict == Verdict.sell:
        return price_change_pct < 0
    return abs(price_change_pct) <= settings.verdict_outcome_hold_band_pct
