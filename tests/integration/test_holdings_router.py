import httpx
import pytest
import respx

from app.config import settings
from app.db.models import Company, Holding


def _mock_finnhub_success(name="Holding Co"):
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=httpx.Response(200, json={"name": name, "exchange": "NASDAQ"})
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=httpx.Response(200, json={"c": 15, "o": 14, "h": 16, "l": 13, "pc": 14})
    )
    respx.get("https://finnhub.io/api/v1/company-news").mock(return_value=httpx.Response(200, json=[]))


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch):
    monkeypatch.setattr(settings, "finnhub_api_key", "finnhub-key")
    monkeypatch.setattr(settings, "alpha_vantage_api_key", None)


def test_list_holdings_empty(client):
    response = client.get("/holdings")

    assert response.status_code == 200
    assert response.json() == []


@respx.mock
def test_upsert_holding_creates_position(client, db_session):
    _mock_finnhub_success()

    response = client.post("/holdings/zhr", json={"shares": 5, "cost_basis_per_share": 20.0})

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "ZHR"
    assert body["shares"] == 5.0
    company = db_session.query(Company).filter_by(ticker="ZHR").one()
    assert db_session.query(Holding).filter_by(company_id=company.id).one_or_none() is not None


def test_upsert_holding_rejects_non_positive_shares(client):
    response = client.post("/holdings/zhr", json={"shares": 0, "cost_basis_per_share": 20.0})

    assert response.status_code == 422


@respx.mock
def test_remove_holding_is_idempotent(client):
    _mock_finnhub_success()
    client.post("/holdings/zhr", json={"shares": 5, "cost_basis_per_share": 20.0})

    response = client.delete("/holdings/zhr")

    assert response.status_code == 200
    assert response.json() == {"ticker": "ZHR", "removed": True}

    second = client.delete("/holdings/zhr")
    assert second.status_code == 200


@respx.mock
def test_wiki_reflects_position_once_held(client):
    _mock_finnhub_success()
    response = client.post("/holdings/zhr", json={"shares": 5, "cost_basis_per_share": 20.0})
    assert response.status_code == 200

    wiki_response = client.get("/companies/ZHR/wiki")

    assert wiki_response.status_code == 200
    holding = wiki_response.json()["holding"]
    assert holding is not None
    assert holding["shares"] == 5.0
