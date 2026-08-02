from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://trader:trader@localhost:5432/trader"
    finnhub_api_key: str | None = None
    gemini_api_key: str | None = None


settings = Settings()
