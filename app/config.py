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

    # Ticker directory (Post-Phase-5 Addition #2) -- the local autocomplete index is bulk-
    # refreshed weekly, deliberately far slower than the price/news cadence: the symbol
    # universe barely changes day to day, and one bulk pull costs a single provider slot.
    ticker_directory_refresh_interval_seconds: int = 604800

    # AI pipeline (Phase 4). gemini-flash-latest is a moving alias (spec.md open decision #2)
    # -- kept as a config knob rather than hardcoded so it can be pinned to an explicit
    # version later without a code change, and the exact model used per call is stamped into
    # ai_analyses.context_snapshot for reproducibility (NFR-5).
    gemini_model: str = "gemini-flash-latest"
    gemini_rate_limit_per_window: int = 100
    gemini_rate_limit_window_seconds: int = 86400
    # Budget priority (FR-17, FR-20): on-demand and critique get throttled before the full
    # daily budget is exhausted, reserving headroom for higher-priority callers.
    gemini_on_demand_budget_fraction: float = 0.7
    gemini_critique_budget_fraction: float = 0.4
    # Chat (Post-Phase-5 addition) is the lowest-priority consumer of the daily budget --
    # a burst of chat questions must never starve scheduled verdicts, on-demand analysis, or
    # critiques, all of which are the app's core purpose.
    gemini_chat_budget_fraction: float = 0.2

    # Chat grounding payload size (token-efficiency pass, 2026-08-05). Chat builds the largest
    # prompt in this app -- one entry per tracked company, reassembled on *every* message -- so
    # unlike the once-daily verdict call it is the one path that can hit a token-per-minute
    # limit or slow down while the user is waiting. Recent news is ~2/3 of the payload, so these
    # are the real dials: lower them to make each message cheaper, raise them for richer
    # answers. Deliberately config, not hardcoded, because it is a quality/cost tradeoff only
    # the user can judge -- same reasoning as the budget fractions above.
    # NOTE: 6 is the effective ceiling for articles-per-company -- wiki_service.assemble() reads
    # 6 (ingest_service.recent_news limit), so raising this alone has no effect.
    chat_news_articles_per_company: int = 6
    chat_article_summary_chars: int = 400
    chat_description_chars: int = 300
    chat_max_tracked_companies: int = 40
    chat_max_history_messages: int = 20

    # Verdict track record: checks whether verdicts/confidence are actually calibrated
    # against what price did afterward, rather than trusting the AI's self-reported
    # confidence at face value.
    verdict_outcome_horizon_days: int = 30
    verdict_outcome_hold_band_pct: float = 5.0
    outcome_scheduler_interval_seconds: int = 86400

    # Historical backfill on watchlist promote (Alpha Vantage TIME_SERIES_DAILY, compact --
    # outputsize=full is premium-gated, confirmed live 2026-08-03). Skipped if a company
    # already has at least this many price_bars rows, so re-promoting or already-tracked
    # tickers don't spend Alpha Vantage's scarce ~25/day free-tier budget for nothing.
    backfill_min_bars_threshold: int = 50


settings = Settings()
