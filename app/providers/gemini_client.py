"""Wraps google-genai for schema-forced JSON verdict/critique generation (spec.md T4.1).

Not a DataProvider -- Gemini isn't a fallback-swappable data source, it's the single AI
reasoning step, so it doesn't need the two-provider interface the market-data clients share.
Still raises the same Transient/PermanentProviderError taxonomy so it composes with the
existing rate-limiter/retry machinery in provider_orchestrator-style callers.
"""
import json

from app.providers.base import PermanentProviderError, TransientProviderError

DEFAULT_TIMEOUT_MS = 30_000


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        if not api_key:
            raise PermanentProviderError("Gemini API key is not configured")

        from google import genai
        from google.genai import types

        self.model = model
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=timeout_ms))

    def generate_json(self, prompt_text: str, schema: dict) -> dict:
        from google.genai import errors, types

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=schema,
                ),
            )
        except errors.ClientError as exc:
            if exc.code == 429:
                raise TransientProviderError(f"Gemini rate limit/quota exceeded: {exc}") from exc
            raise PermanentProviderError(f"Gemini request rejected: {exc}") from exc
        except errors.ServerError as exc:
            raise TransientProviderError(f"Gemini server error: {exc}") from exc
        except errors.APIError as exc:
            raise TransientProviderError(f"Gemini request failed: {exc}") from exc

        try:
            return json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PermanentProviderError(
                f"Gemini returned invalid JSON despite response_schema: {exc}"
            ) from exc
