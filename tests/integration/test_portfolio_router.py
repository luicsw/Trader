from app.db.models import AiAnalysis, AnalysisTrigger, Company, CoverageTier, Holding, Verdict


def _seed_eligible(db, ticker, shares, cost, sell, min_hold=5):
    company = Company(ticker=ticker, name=f"{ticker} Inc", sector="Technology", coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.flush()
    db.add(Holding(company_id=company.id, shares=shares, cost_basis_per_share=cost))
    db.add(
        AiAnalysis(
            company_id=company.id,
            verdict=Verdict.buy,
            confidence=0.7,
            reasoning_text="seed",
            price_targets={"buy_at_or_below": None, "sell_at_or_above": sell, "stop_loss": None},
            hold_period_days={"min": min_hold, "max": None, "note": None},
            cited_sources=[],
            context_snapshot={},
            trigger=AnalysisTrigger.on_demand,
        )
    )
    db.flush()


def test_projected_income_default_returns_all_horizons(client, db_session):
    _seed_eligible(db_session, "ZQA", shares=10, cost=12.0, sell=20.0)

    response = client.get("/portfolio/projected-income")

    assert response.status_code == 200
    body = response.json()
    assert [b["horizon_days"] for b in body["horizons"]] == [30, 60, 90]
    row = body["horizons"][0]["holdings"][0]
    assert row["ticker"] == "ZQA"
    assert row["expected_profit"] == 80.0


def test_horizon_filter_returns_single_horizon(client, db_session):
    _seed_eligible(db_session, "ZQB", shares=1, cost=10.0, sell=15.0)

    response = client.get("/portfolio/projected-income?horizon=60")

    assert response.status_code == 200
    body = response.json()
    assert [b["horizon_days"] for b in body["horizons"]] == [60]


def test_tickers_filter_narrows_holdings(client, db_session):
    _seed_eligible(db_session, "ZQC", shares=1, cost=10.0, sell=15.0)
    _seed_eligible(db_session, "ZQD", shares=1, cost=10.0, sell=15.0)

    response = client.get("/portfolio/projected-income?tickers=ZQC")

    assert response.status_code == 200
    body = response.json()
    tickers = [r["ticker"] for r in body["horizons"][0]["holdings"]]
    assert tickers == ["ZQC"]
