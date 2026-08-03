import json
from unittest.mock import MagicMock

import pytest

from app.providers.base import PermanentProviderError, TransientProviderError
from app.providers.gemini_client import GeminiClient


def _client_with_mocked_response(response_text=None, side_effect=None):
    client = GeminiClient(api_key="test-key", model="test-model")
    mock_generate = MagicMock()
    if side_effect is not None:
        mock_generate.side_effect = side_effect
    else:
        mock_response = MagicMock()
        mock_response.text = response_text
        mock_generate.return_value = mock_response
    client._client.models.generate_content = mock_generate
    return client


def test_generate_json_returns_parsed_response():
    client = _client_with_mocked_response(response_text=json.dumps({"verdict": "hold"}))

    result = client.generate_json("prompt", {"type": "object"})

    assert result == {"verdict": "hold"}


def test_generate_json_invalid_json_raises_permanent_error():
    client = _client_with_mocked_response(response_text="not valid json")

    with pytest.raises(PermanentProviderError):
        client.generate_json("prompt", {"type": "object"})


def test_generate_json_rate_limit_raises_transient_error():
    from google.genai import errors

    error = errors.ClientError(code=429, response_json={"error": {"message": "quota exceeded"}})
    client = _client_with_mocked_response(side_effect=error)

    with pytest.raises(TransientProviderError):
        client.generate_json("prompt", {"type": "object"})


def test_generate_json_auth_failure_raises_permanent_error():
    from google.genai import errors

    error = errors.ClientError(code=403, response_json={"error": {"message": "invalid key"}})
    client = _client_with_mocked_response(side_effect=error)

    with pytest.raises(PermanentProviderError):
        client.generate_json("prompt", {"type": "object"})


def test_generate_json_server_error_raises_transient_error():
    from google.genai import errors

    error = errors.ServerError(code=503, response_json={"error": {"message": "unavailable"}})
    client = _client_with_mocked_response(side_effect=error)

    with pytest.raises(TransientProviderError):
        client.generate_json("prompt", {"type": "object"})


def test_missing_api_key_raises_permanent_error_immediately():
    with pytest.raises(PermanentProviderError):
        GeminiClient(api_key="", model="test-model")
