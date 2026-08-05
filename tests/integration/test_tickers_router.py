from app.db.models import TickerDirectory


def _seed(db, rows):
    for row in rows:
        db.add(TickerDirectory(**row))
    db.flush()


def test_search_returns_matches(client, db_session):
    _seed(
        db_session,
        [
            {"symbol": "AAPL", "name": "Apple Inc", "exchange": "XNAS", "security_type": "Common Stock"},
            {"symbol": "TSLA", "name": "Tesla Inc", "exchange": "XNAS", "security_type": "Common Stock"},
        ],
    )

    response = client.get("/tickers/search?q=AAP")

    assert response.status_code == 200
    body = response.json()
    assert body == [
        {"symbol": "AAPL", "name": "Apple Inc", "exchange": "XNAS", "security_type": "Common Stock"}
    ]


def test_search_blank_query_returns_empty(client):
    response = client.get("/tickers/search?q=   ")

    assert response.status_code == 200
    assert response.json() == []


def test_search_respects_limit(client, db_session):
    _seed(
        db_session,
        [{"symbol": f"AA{i}", "name": f"Co {i}", "exchange": "XNAS", "security_type": "Common Stock"} for i in range(5)],
    )

    response = client.get("/tickers/search?q=AA&limit=2")

    assert response.status_code == 200
    assert len(response.json()) == 2
