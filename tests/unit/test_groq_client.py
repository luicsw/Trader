import json
from unittest.mock import MagicMock

import httpx
import pytest

from app.providers.base import PermanentProviderError, TransientProviderError
from app.providers.groq_client import GroqClient, is_available


def _envelope(content: str) -> dict:
    """The OpenAI-compatible chat-completions response shape Groq returns."""
    return {"choices": [{"message": {"content": content}}]}


def _client_with_response(status_code=200, json_body=None, text="", side_effect=None):
    client = GroqClient(api_key="test-key", model="test-model")
    mock_post = MagicMock()
    if side_effect is not None:
        mock_post.side_effect = side_effect
    else:
        mock_post.return_value = httpx.Response(status_code, json=json_body) if json_body is not None else httpx.Response(status_code, text=text)
    client._client.post = mock_post
    return client


def test_is_available_reflects_key_presence():
    assert is_available("some-key") is True
    assert is_available("") is False
    assert is_available(None) is False


def test_missing_api_key_raises_permanent_error_immediately():
    with pytest.raises(PermanentProviderError):
        GroqClient(api_key="", model="test-model")


def test_generate_json_returns_parsed_forecast():
    forecast = {"forecasts": [{"horizon_days": 30, "expected_low": 100, "expected_high": 120}]}
    client = _client_with_response(json_body=_envelope(json.dumps(forecast)))

    result = client.generate_json("prompt")

    assert result == forecast


def test_generate_json_invalid_json_content_raises_permanent_error():
    client = _client_with_response(json_body=_envelope("not valid json"))

    with pytest.raises(PermanentProviderError):
        client.generate_json("prompt")


def test_generate_json_unexpected_envelope_raises_permanent_error():
    client = _client_with_response(json_body={"unexpected": "shape"})

    with pytest.raises(PermanentProviderError):
        client.generate_json("prompt")


def test_generate_json_rate_limit_raises_transient_error():
    client = _client_with_response(status_code=429, text="rate limited")

    with pytest.raises(TransientProviderError):
        client.generate_json("prompt")


def test_generate_json_auth_failure_raises_permanent_error():
    client = _client_with_response(status_code=401, text="invalid key")

    with pytest.raises(PermanentProviderError):
        client.generate_json("prompt")


def test_generate_json_server_error_raises_transient_error():
    client = _client_with_response(status_code=503, text="unavailable")

    with pytest.raises(TransientProviderError):
        client.generate_json("prompt")


def test_generate_json_timeout_raises_transient_error():
    client = _client_with_response(side_effect=httpx.TimeoutException("timed out"))

    with pytest.raises(TransientProviderError):
        client.generate_json("prompt")
