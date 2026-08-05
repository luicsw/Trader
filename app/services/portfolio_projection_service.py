"""Portfolio income projection (Post-Phase-5 Addition #2) -- answers "what would I make if I
sold within 30/60/90 days?" for the whole portfolio, one stock, or an arbitrary subset. Pure
computation over data already collected: the user's `holdings` plus the latest `ai_analyses`
row per company. No new AI call and no provider call. See spec.md FR-27 to FR-29.

This panel means exactly one thing: "expected profit if you keep holding and sell when the AI's
upside target is reached within horizon H." Eligibility (FR-28): a holding contributes to
horizon H only if its latest verdict is buy/hold with a non-null `sell_at_or_above` AND the AI's
own suggested `hold_period_days.min` is <= H. A `sell` verdict does not fit that premise -- it
says "get out now", not "wait for this upside target" (which the prompt anchors near resistance),
so projecting profit there would show a hopeful gain that contradicts the advice; sell verdicts
are excluded with a reason pointing at the holding's current gain/loss, already shown on the
page. Any other ineligible case (no analysis, no target, target too far out) is null with its own
explicit reason, never silently omitted or zeroed.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AiAnalysis, Company, Holding, Verdict

DEFAULT_HORIZONS = (30, 60, 90)

_REASON_NO_ANALYSIS = "not yet analyzed"
_REASON_NO_TARGET = "no AI sell target"
_REASON_HOLD_LONGER = "AI suggests holding longer than this horizon"
_REASON_SELL_NOW = "AI recommends selling now — see current gain/loss"


def compute_projected_income(
    db: Session,
    tickers: list[str] | None = None,
    horizons: tuple[int, ...] | list[int] = DEFAULT_HORIZONS,
) -> dict:
    holdings = _holdings(db, tickers)
    latest = _latest_analyses(db, [holding.company_id for holding in holdings])

    horizon_blocks = []
    for horizon in horizons:
        rows = [
            _project_holding(holding, latest.get(holding.company_id), horizon)
            for holding in holdings
        ]
        total = sum(row["expected_profit"] for row in rows if row["expected_profit"] is not None)
        eligible_count = sum(1 for row in rows if row["eligible"])
        horizon_blocks.append(
            {
                "horizon_days": horizon,
                "total_expected_profit": total,
                "eligible_count": eligible_count,
                "holdings": rows,
            }
        )
    return {"horizons": horizon_blocks}


def _holdings(db: Session, tickers: list[str] | None) -> list[Holding]:
    stmt = select(Holding).join(Company, Holding.company_id == Company.id).order_by(Company.ticker)
    if tickers:
        stmt = stmt.where(Company.ticker.in_([ticker.upper() for ticker in tickers]))
    return list(db.scalars(stmt).all())


def _latest_analyses(db: Session, company_ids: list[int]) -> dict[int, AiAnalysis]:
    """Latest ai_analyses row per company in one DISTINCT ON query (same pattern as
    chat_service._latest_verdicts), not one query per holding.
    """
    if not company_ids:
        return {}
    rows = db.scalars(
        select(AiAnalysis)
        .where(AiAnalysis.company_id.in_(company_ids))
        .distinct(AiAnalysis.company_id)
        .order_by(AiAnalysis.company_id, AiAnalysis.generated_at.desc())
    ).all()
    return {row.company_id: row for row in rows}


def _project_holding(holding: Holding, analysis: AiAnalysis | None, horizon: int) -> dict:
    shares = float(holding.shares)
    cost = float(holding.cost_basis_per_share)
    row = {
        "ticker": holding.company.ticker,
        "name": holding.company.name,
        "shares": shares,
        "cost_basis_per_share": cost,
        "sell_at_or_above": None,
        "expected_profit": None,
        "eligible": False,
        "reason": None,
    }

    if analysis is None:
        row["reason"] = _REASON_NO_ANALYSIS
        return row

    sell_target = (analysis.price_targets or {}).get("sell_at_or_above")
    row["sell_at_or_above"] = sell_target

    # A `sell` verdict means "get out now", not "wait for this upside target" -- so projecting
    # profit at sell_at_or_above (anchored near resistance by the verdict prompt) would show a
    # hopeful gain that contradicts the advice. Exclude it; the honest "what would I get if I
    # sold today" figure is the holding's unrealized gain/loss already shown on the page. This
    # is also the only case where hold_period_days.min is null (schema), so keying on the verdict
    # is clearer than inferring it from a null min.
    if analysis.verdict == Verdict.sell:
        row["reason"] = _REASON_SELL_NOW
        return row

    if sell_target is None:
        row["reason"] = _REASON_NO_TARGET
        return row

    min_hold = (analysis.hold_period_days or {}).get("min")
    if min_hold is not None and min_hold > horizon:
        row["reason"] = _REASON_HOLD_LONGER
        return row

    row["expected_profit"] = (float(sell_target) - cost) * shares
    row["eligible"] = True
    return row
