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


# --- Grounding payload shape (token-efficiency pass, 2026-08-05) ---------------------------
#
# Chat is the only prompt whose size scales with how many companies the user tracks, and it is
# rebuilt on every message, so these assert the payload stays a purpose-built subset rather than
# drifting back to the full wiki_service.assemble() dict.


def test_slim_grounding_drops_page_only_and_duplicated_fields():
    wiki = {
        "ticker": "ZCH2",
        "name": "Slim Co",
        "description": "d" * 500,
        "logo_url": "https://example.com/logo.png",
        "coverage_tier": "watchlist",
        "sections": {
            "overview": {"body": "prose restating name/exchange/sector"},
            "key_metrics": {"body": "prose restating price/market cap"},
            "news_digest": {"body": "- bullet list of the same headlines"},
        },
        "recent_news": [
            {"headline": "H1", "summary": "s" * 900, "url": "https://example.com/a1",
             "source": "Reuters", "published_at": "2026-08-01T00:00:00+00:00", "sentiment": "positive"},
        ],
    }

    slim = chat_service._slim_for_grounding(wiki, None)

    # The three wiki_sections bodies each restate structured fields already in the payload.
    assert "sections" not in slim
    # Unusable by a text model / internal bookkeeping.
    assert "logo_url" not in slim
    assert "coverage_tier" not in slim
    # Citations resolve server-side from reference ids, so the model never needs URLs.
    assert "url" not in slim["recent_news"][0]
    # Free-text fields are capped so one verbose company can't inflate every future message.
    assert len(slim["description"]) <= settings.chat_description_chars + 3
    assert len(slim["recent_news"][0]["summary"]) <= settings.chat_article_summary_chars + 3
    # ...while everything the model actually reasons with survives.
    assert slim["ticker"] == "ZCH2"
    assert slim["recent_news"][0]["headline"] == "H1"
    assert slim["recent_news"][0]["sentiment"] == "positive"


def test_slim_grounding_respects_articles_per_company_cap(monkeypatch):
    monkeypatch.setattr(settings, "chat_news_articles_per_company", 2)
    wiki = {
        "ticker": "ZCH3",
        "recent_news": [{"headline": f"H{i}", "summary": None} for i in range(6)],
    }

    slim = chat_service._slim_for_grounding(wiki, None)

    assert [a["headline"] for a in slim["recent_news"]] == ["H0", "H1"]


def test_grounding_context_includes_latest_verdict_per_company(db_session):
    from app.db.models import AiAnalysis, AnalysisTrigger, Verdict

    company = _seed_company(db_session, ticker="ZCH4")
    older = AiAnalysis(
        company_id=company.id, verdict=Verdict.hold, confidence=0.3, reasoning_text="older",
        price_targets={}, hold_period_days={}, cited_sources=[], context_snapshot={},
        trigger=AnalysisTrigger.on_demand, generated_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    newer = AiAnalysis(
        company_id=company.id, verdict=Verdict.buy, confidence=0.8, reasoning_text="newer",
        price_targets={"sell_at_or_above": 120.0}, hold_period_days={"min": 30},
        cited_sources=[], context_snapshot={}, trigger=AnalysisTrigger.on_demand,
        generated_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    db_session.add_all([older, newer])
    db_session.commit()

    verdicts = chat_service._latest_verdicts(db_session, [company.id])

    # The chat prompt has always instructed the model to use each company's latest verdict;
    # before this pass the payload never carried one at all.
    assert verdicts[company.id]["verdict"] == "buy"
    assert verdicts[company.id]["confidence"] == 0.8


def test_latest_verdicts_is_empty_for_never_analyzed_company(db_session):
    company = _seed_company(db_session, ticker="ZCH5")

    assert chat_service._latest_verdicts(db_session, [company.id]) == {}
    assert chat_service._latest_verdicts(db_session, []) == {}
