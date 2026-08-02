from abc import ABC, abstractmethod


class ProviderError(Exception):
    """A provider call failed. Callers decide retry/fallback policy (Phase 3) --
    this only distinguishes what happened, not what to do about it."""


class DataProvider(ABC):
    @abstractmethod
    def get_profile(self, ticker: str) -> dict:
        ...

    @abstractmethod
    def get_quote(self, ticker: str) -> dict:
        ...
