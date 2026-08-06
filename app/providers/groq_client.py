"""Groq client for the multi-horizon price forecast (Post-Phase-5 Addition #2, spec.md
FR-30/FR-33).

SHIPS DORMANT and UNVALIDATED: no API key is obtainable as of 2026-08-05, so unlike every
other integration in this project this client, its prompt, and its response parsing were
written on assumption rather than after a live derisk run (spec.md FR-33b). Expect the first
real call to need adjustment -- that's tracked in spec.md's "Groq activation" checklist.

Deliberately built against Groq's OpenAI-compatible REST endpoint with plain httpx (already a
dependency), not the `groq` SDK -- one fewer dependency for a feature that may never activate,
and it mirrors the finnhub/alpha_vantage httpx pattern. Like GeminiClient this is NOT a
DataProvider (Groq isn't a fallback-swappable data source), but it raises the same
Transient/Permanent taxonomy so it composes with the existing rate-limiter/retry machinery.

`is_available()` lets callers (forecast_service) short-circuit on a missing key *before* any
network attempt or limiter check -- so a dormant key is a non-event: nothing to log, nothing
to trip a breaker, no provider_call_log row written (spec.md NFR-9/FR-33a).
"""
import json

import httpx

from app.providers.base import PermanentProviderError, TransientProviderError

BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_TIMEOUT = 30.0


def is_available(api_key: str | None) -> bool:
    """True only if a Groq key is configured. The single source callers consult before any
    network work, so the dormant (no-key) path never reaches the retry or circuit-breaker
    machinery (spec.md FR-33a)."""
    return bool(api_key)


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout: float = DEFAULT_TIMEOUT):
        if not api_key:
            # Mirrors GeminiClient: a missing key is a permanent, retry-won't-help condition.
            # Callers are expected to check is_available() first and never construct this
            # without a key -- this is the belt-and-suspenders guard (spec.md FR-33a).
            raise PermanentProviderError("Groq API key is not configured")
        self._api_key = api_key
        self.model = model
        self._client = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def generate_json(self, prompt_text: str) -> dict:
        """Sends the prompt to Groq's chat-completions endpoint in JSON-object mode and returns
        the parsed object. The prompt itself carries the required output shape (Groq's
        json_object mode enforces valid JSON but not a schema), so it must instruct the model
        to emit exactly the {forecasts: [...]} structure forecast_service expects.
        """
        try:
            response = self._client.post(
                "/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt_text}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.4,
                },
            )
        except httpx.TimeoutException as exc:
            raise TransientProviderError("Groq request timed out") from exc
        except httpx.TransportError as exc:
            raise TransientProviderError(f"Groq request failed: {exc}") from exc

        self._raise_for_status(response)

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise PermanentProviderError(f"Groq returned an unexpected response envelope: {exc}") from exc

        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PermanentProviderError(
                f"Groq returned invalid JSON despite json_object mode: {exc}"
            ) from exc

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code in (401, 403):
            raise PermanentProviderError("Groq authentication failed -- check GROQ_API_KEY")
        if response.status_code == 429:
            raise TransientProviderError("Groq rate limit/quota exceeded")
        if response.status_code >= 500:
            raise TransientProviderError(f"Groq server error: {response.status_code}")
        if response.is_error:
            raise PermanentProviderError(
                f"Groq request rejected: {response.status_code} {response.text}"
            )
