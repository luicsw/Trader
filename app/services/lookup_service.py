"""lookup_service.get_or_fetch(ticker) -- the any-company lookup tier (spec.md FR-9).

Serves straight from Postgres when a company row is fresh enough; otherwise fetches via the
shared fetch_with_fallback orchestrator (Finnhub -> Alpha Vantage, rate-limited and circuit-
broken), upserts, and regenerates wiki_sections -- all without touching `watchlist`, so
lookup tickers get no recurring job. Every fetch attempt is recorded in job_runs so failures
are visible, never silent (NFR-4).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Company, JobRun, JobStatus
from app.providers.base import ProviderError
from app.services import ingest_service, provider_orchestrator, wiki_sections_service, wiki_service


def get_or_fetch(db: Session, ticker: str) -> dict:
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))

    if company is None or _is_stale(company):
        try:
            company = _fetch_and_upsert(db, ticker)
        except ProviderError as exc:
            db.add(JobRun(job_name=f"lookup:{ticker}", status=JobStatus.failure, error_message=str(exc)))
            db.commit()
            raise

        articles = provider_orchestrator.fetch_news_best_effort(db, ticker)
        ingest_service.upsert_news(db, company.id, articles)

        bar = ingest_service.latest_bar(db, company.id)
        wiki_sections_service.generate_sections(db, company, bar)
        db.add(JobRun(job_name=f"lookup:{ticker}", status=JobStatus.success))
        db.commit()

    wiki = wiki_service.assemble(db, ticker)
    assert wiki is not None, "just upserted this company -- assemble() must find it"
    return wiki


def _is_stale(company: Company) -> bool:
    if company.last_profile_refresh_at is None:
        return True
    age = datetime.now(timezone.utc) - company.last_profile_refresh_at
    return age > timedelta(minutes=settings.lookup_stale_after_minutes)


def _fetch_and_upsert(db: Session, ticker: str) -> Company:
    result = provider_orchestrator.fetch_with_fallback(db, ticker)
    return ingest_service.upsert_profile_and_quote(db, ticker, result["profile"], result["quote"])
