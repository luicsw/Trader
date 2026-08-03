from fastapi.testclient import TestClient

from app.main import app


def test_internal_refresh_returns_summary_shape():
    client = TestClient(app)
    response = client.post("/internal/refresh")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"checked", "refreshed", "failed"}
