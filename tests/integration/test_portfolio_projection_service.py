from datetime import datetime, timezone

from app.db.models import AiAnalysis, AnalysisTrigger, Company, CoverageTier, Holding, Verdict
from app.services import portfolio_projection_service as pps


def _company(db, ticker, sector="Technology"):
    company = Company(ticker=ticker, name=f"{ticker} Inc", sector=sector, coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    return company


def _holding(db, company, shares, cost):
    holding = Holding(company_id=company.id, shares=shares, cost_basis_per_share=cost)
    db.add(holding)
    db.flush()
    return holding


def _analysis(db, company, verdict=Verdict.buy, sell=None, min_hold=None, generated_at=None):
    analysis = AiAnalysis(
        company_id=company.id,
        verdict=verdict,
        confidence=0.7,
        reasoning_text="seed",
        price_targets={"buy_at_or_below": None, "sell_at_or_above": sell, "stop_loss": None},
        hold_period_days={"min": min_hold, "max": None, "note": None},
        cited_sources=[],
        context_snapshot={},
        trigger=AnalysisTrigger.on_demand,
    )
    if generated_at is not None:
        analysis.generated_at = generated_at
    db.add(analysis)
    db.flush()
    return analysis


def _row(result, horizon, ticker):
    block = next(b for b in result["horizons"] if b["horizon_days"] == horizon)
    return next(r for r in block["holdings"] if r["ticker"] == ticker)


def _block(result, horizon):
    return next(b for b in result["horizons"] if b["horizon_days"] == horizon)


def test_eligible_holding_projects_expected_profit(db_session):
    company = _company(db_session, "ZPA")
    _holding(db_session, company, shares=10, cost=12.0)
    _analysis(db_session, company, sell=20.0, min_hold=15)

    result = pps.compute_projected_income(db_session, horizons=(30,))

    row = _row(result, 30, "ZPA")
    assert row["eligible"] is True
    assert row["reason"] is None
    assert row["expected_profit"] == (20.0 - 12.0) * 10  # 80
    block = _block(result, 30)
    assert block["total_expected_profit"] == 80.0
    assert block["eligible_count"] == 1


def test_no_analysis_is_ineligible_with_reason(db_session):
    company = _company(db_session, "ZPB")
    _holding(db_session, company, shares=5, cost=10.0)

    result = pps.compute_projected_income(db_session, horizons=(30,))

    row = _row(result, 30, "ZPB")
    assert row["eligible"] is False
    assert row["expected_profit"] is None
    assert row["reason"] == "not yet analyzed"


def test_no_sell_target_is_ineligible_with_reason(db_session):
    company = _company(db_session, "ZPC")
    _holding(db_session, company, shares=5, cost=10.0)
    _analysis(db_session, company, verdict=Verdict.hold, sell=None, min_hold=10)

    row = _row(pps.compute_projected_income(db_session, horizons=(30,)), 30, "ZPC")
    assert row["eligible"] is False
    assert row["expected_profit"] is None
    assert row["reason"] == "no AI sell target"


def test_hold_period_longer_than_horizon_buckets_correctly(db_session):
    company = _company(db_session, "ZPD")
    _holding(db_session, company, shares=2, cost=100.0)
    _analysis(db_session, company, sell=150.0, min_hold=45)

    result = pps.compute_projected_income(db_session, horizons=(30, 60))

    # 45-day min hold: ineligible at 30d, eligible at 60d -- the whole point of the bucketing.
    row30 = _row(result, 30, "ZPD")
    assert row30["eligible"] is False
    assert row30["reason"] == "AI suggests holding longer than this horizon"
    assert row30["expected_profit"] is None
    row60 = _row(result, 60, "ZPD")
    assert row60["eligible"] is True
    assert row60["expected_profit"] == (150.0 - 100.0) * 2  # 100


def test_sell_verdict_is_excluded_with_sell_now_reason(db_session):
    # A sell verdict says "get out now", not "wait for the upside target" -- so it's excluded
    # from this target-based projection, with a reason pointing at the current gain/loss the page
    # already shows, rather than a hopeful gain at a resistance target the verdict contradicts.
    company = _company(db_session, "ZPE")
    _holding(db_session, company, shares=3, cost=50.0)
    _analysis(db_session, company, verdict=Verdict.sell, sell=60.0, min_hold=None)

    row = _row(pps.compute_projected_income(db_session, horizons=(30,)), 30, "ZPE")
    assert row["eligible"] is False
    assert row["expected_profit"] is None
    assert row["reason"] == "AI recommends selling now — see current gain/loss"


def test_expected_loss_on_buy_hold_is_shown_as_negative_not_hidden(db_session):
    # Sell target below cost basis on a hold verdict: eligible, honest negative "profit" (you'd
    # lock in a loss even if the target is hit) -- never zeroed or dropped.
    company = _company(db_session, "ZPL")
    _holding(db_session, company, shares=2, cost=100.0)
    _analysis(db_session, company, verdict=Verdict.hold, sell=90.0, min_hold=10)

    row = _row(pps.compute_projected_income(db_session, horizons=(30,)), 30, "ZPL")
    assert row["eligible"] is True
    assert row["expected_profit"] == (90.0 - 100.0) * 2  # -20


def test_uses_latest_analysis_not_an_older_one(db_session):
    company = _company(db_session, "ZPF")
    _holding(db_session, company, shares=1, cost=10.0)
    _analysis(
        db_session, company, sell=99.0, min_hold=5,
        generated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    _analysis(
        db_session, company, sell=20.0, min_hold=5,
        generated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    row = _row(pps.compute_projected_income(db_session, horizons=(30,)), 30, "ZPF")
    assert row["sell_at_or_above"] == 20.0  # the newer analysis, not 99.0
    assert row["expected_profit"] == (20.0 - 10.0) * 1


def test_aggregate_sums_only_eligible_holdings(db_session):
    eligible = _company(db_session, "ZPG")
    _holding(db_session, eligible, shares=10, cost=12.0)
    _analysis(db_session, eligible, sell=20.0, min_hold=10)

    ineligible = _company(db_session, "ZPH")
    _holding(db_session, ineligible, shares=100, cost=1.0)  # would dwarf the total if wrongly counted
    _analysis(db_session, ineligible, verdict=Verdict.hold, sell=None, min_hold=10)

    block = _block(pps.compute_projected_income(db_session, horizons=(30,)), 30)
    assert block["total_expected_profit"] == 80.0
    assert block["eligible_count"] == 1


def test_tickers_filter_narrows_the_set(db_session):
    a = _company(db_session, "ZPI")
    _holding(db_session, a, shares=1, cost=10.0)
    b = _company(db_session, "ZPJ")
    _holding(db_session, b, shares=1, cost=10.0)

    result = pps.compute_projected_income(db_session, tickers=["zpi"], horizons=(30,))

    tickers = [r["ticker"] for r in _block(result, 30)["holdings"]]
    assert tickers == ["ZPI"]


def test_default_returns_all_three_horizons(db_session):
    result = pps.compute_projected_income(db_session)
    assert [b["horizon_days"] for b in result["horizons"]] == [30, 60, 90]
