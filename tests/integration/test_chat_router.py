from unittest.mock import MagicMock

from app.config import settings
from app.db.models import Company, CoverageTier
from app.providers.base import PermanentProviderError
from app.services import chat_service

REPLY_JSON = {"reply": "Among your tracked companies, ZCH2 looks strongest."}


def _seed_company(db, ticker="ZCH2"):
    company = Company(ticker=ticker, name="Chat Router Co", coverage_tier=CoverageTier.watchlist)
    db.add(company)
    db.commit()
    return company


def _mock_gemini_client(monkeypatch, return_value=None, side_effect=None):
    mock_instance = MagicMock()
    if side_effect is not None:
        mock_instance.generate_json.side_effect = side_effect
    else:
        mock_instance.generate_json.return_value = return_value
    monkeypatch.setattr(chat_service, "GeminiClient", MagicMock(return_value=mock_instance))
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")


def test_list_messages_empty(client):
    response = client.get("/chat/messages")

    assert response.status_code == 200
    assert response.json() == []


def test_send_message_rejects_empty_body(client):
    response = client.post("/chat", json={"message": "   "})

    assert response.status_code == 422


def test_send_message_returns_400_when_nothing_tracked(client, monkeypatch):
    # See test_chat_service.py's equivalent test for why this can't rely on the companies
    # table being empty in the shared dev database.
    monkeypatch.setattr(chat_service, "_build_grounding_context", lambda db: [])

    response = client.post("/chat", json={"message": "what should I buy?"})

    assert response.status_code == 400


def test_send_message_returns_assistant_reply(client, db_session, monkeypatch):
    _seed_company(db_session)
    _mock_gemini_client(monkeypatch, return_value=REPLY_JSON)

    response = client.post("/chat", json={"message": "what's best among my tracked stocks?"})

    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "assistant"
    assert body["content"] == REPLY_JSON["reply"]

    history = client.get("/chat/messages")
    assert len(history.json()) == 2


def test_send_message_returns_502_on_provider_error(client, db_session, monkeypatch):
    _seed_company(db_session)
    _mock_gemini_client(monkeypatch, side_effect=PermanentProviderError("bad json"))

    response = client.post("/chat", json={"message": "hello"})

    assert response.status_code == 502
