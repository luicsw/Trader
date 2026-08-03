from abc import ABC, abstractmethod


class ProviderError(Exception):
    """A provider call failed. Subclasses distinguish transient vs. permanent so the
    fetch-with-fallback orchestrator (Phase 3) can decide retry-then-fallback vs.
    immediate-fallback (spec.md FR-2, FR-3)."""


class TransientProviderError(ProviderError):
    """Timeout, 5xx, or rate-limit (429) -- worth retrying with backoff before falling
    back to the other provider."""


class PermanentProviderError(ProviderError):
    """Bad ticker, auth failure, missing config -- retrying won't help; skip straight to
    fallback (or fail outright if no fallback is left) and log loudly."""


class DataProvider(ABC):
    """Every implementation returns a normalized shape regardless of provider so callers
    never need to know which provider actually answered:
    - get_profile: {name, exchange, sector, logo_url, market_cap}
    - get_quote: {open, high, low, close, previous_close}
    """

    @abstractmethod
    def get_profile(self, ticker: str) -> dict:
        ...

    @abstractmethod
    def get_quote(self, ticker: str) -> dict:
        ...
