from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://trader:trader@localhost:5433/trader"
    finnhub_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    gemini_api_key: str | None = None
    lookup_stale_after_minutes: int = 60

    # Reliability mechanics (plan.md "Reliability mechanics") -- budgeted conservatively
    # below each provider's documented free-tier cap.
    finnhub_rate_limit_per_window: int = 50
    finnhub_rate_limit_window_seconds: int = 60
    alpha_vantage_rate_limit_per_window: int = 20
    alpha_vantage_rate_limit_window_seconds: int = 86400
    circuit_breaker_failure_threshold: int = 3
    circuit_breaker_cooldown_seconds: int = 300

    watchlist_default_refresh_interval_minutes: int = 20
    scheduler_interval_seconds: int = 300


settings = Settings()
