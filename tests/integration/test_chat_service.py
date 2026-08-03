from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.db.models import CallStatus, ChatMessage, ChatRole, Company, CoverageTier, ProviderCallLog, ProviderName
from app.providers.base import PermanentProviderError
from app.services import chat_service

REPLY_JSON = {"reply": "Based on your tracked companies, ZCH1 looks strongest right now."}


def _seed_company(db, ticker="ZCH1"):
    company = Company(ticker=ticker, name="Chat Co", sector="Technology", coverage_tier=CoverageTier.watchlist)
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
    return mock_instance


def test_send_message_raises_when_nothing_is_tracked(db_session, monkeypatch):
    # The shared dev database may already have real, previously-committed Company rows from
    # past live-verification drills (chat grounding deliberately queries ALL companies, not
    # just this test's own -- see chat_service's module docstring), so "nothing tracked" is
    # tested by forcing an empty grounding context directly rather than assuming the
    # companies table is empty (same lesson as this project's ai_analyses test-scoping fix).
    monkeypatch.setattr(chat_service, "_build_grounding_context", lambda db: [])

    with pytest.raises(chat_service.NoTrackedCompaniesError):
        chat_service.send_message(db_session, "what should I buy?")

    assert db_session.query(ChatMessage).count() == 0


def test_send_message_persists_user_and_assistant_messages(db_session, monkeypatch):
    _seed_company(db_session)
    _mock_gemini_client(monkeypatch, return_value=REPLY_JSON)

    reply = chat_service.send_message(db_session, "what's the best tech stock I track?")

    assert reply.role == ChatRole.assistant
    assert reply.content == REPLY_JSON["reply"]
    messages = db_session.query(ChatMessage).order_by(ChatMessage.created_at).all()
    assert len(messages) == 2
    assert messages[0].role == ChatRole.user
    assert messages[0].content == "what's the best tech stock I track?"
    assert messages[1].role == ChatRole.assistant


def test_send_message_records_success_in_provider_call_log(db_session, monkeypatch):
    _seed_company(db_session)
    _mock_gemini_client(monkeypatch, return_value=REPLY_JSON)

    chat_service.send_message(db_session, "hello")

    log = db_session.query(ProviderCallLog).filter_by(provider=ProviderName.gemini).one()
    assert log.status == CallStatus.success


def test_send_message_provider_error_still_persists_user_message_but_not_a_reply(db_session, monkeypatch):
    _seed_company(db_session)
    _mock_gemini_client(monkeypatch, side_effect=PermanentProviderError("bad json"))

    with pytest.raises(PermanentProviderError):
        chat_service.send_message(db_session, "hello")

    messages = db_session.query(ChatMessage).all()
    assert len(messages) == 1
    assert messages[0].role == ChatRole.user


def test_send_message_blocked_once_chat_budget_exhausted(db_session):
    _seed_company(db_session)
    chat_limit = int(settings.gemini_rate_limit_per_window * settings.gemini_chat_budget_fraction)
    now = datetime.now(timezone.utc)
    for _ in range(chat_limit):
        db_session.add(ProviderCallLog(provider=ProviderName.gemini, status=CallStatus.success, called_at=now))
    db_session.commit()

    with pytest.raises(chat_service.QuotaExhaustedError):
        chat_service.send_message(db_session, "hello")

    assert db_session.query(ChatMessage).count() == 0


def test_list_messages_returns_chronological_order(db_session):
    _seed_company(db_session)
    db_session.add(ChatMessage(role=ChatRole.user, content="first"))
    db_session.commit()
    db_session.add(ChatMessage(role=ChatRole.assistant, content="second"))
    db_session.commit()

    messages = chat_service.list_messages(db_session)

    assert [m.content for m in messages] == ["first", "second"]
