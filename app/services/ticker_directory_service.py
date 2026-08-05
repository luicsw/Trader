"""Local ticker directory (Post-Phase-5 Addition #2) -- backs the Add Holding type-ahead
(spec.md FR-34/FR-35) from a locally cached copy of the tradable US symbol universe, so
autocomplete never spends live provider search quota per keystroke. Bulk-refreshed weekly
from Finnhub's /stock/symbol listing via the same dual-trigger pattern as every other job
(NFR-1): POST /internal/refresh-ticker-directory + an APScheduler job, both calling
refresh_directory().

search() reads this table only -- zero live provider calls -- so it is safe to hit on every
keystroke. Plain prefix ILIKE (no pg_trgm): for a single user typing a ticker fragment, a
prefix match on symbol is exactly the wanted behavior, and 31k rows is trivial to scan.
"""
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import CallStatus, JobRun, JobStatus, ProviderName, TickerDirectory
from app.providers.finnhub_client import FinnhubClient
from app.services import circuit_breaker, rate_limiter

_UPSERT_CHUNK_SIZE = 1000
_JOB_NAME = "refresh_ticker_directory"


def search(db: Session, query: str, limit: int = 10) -> list[dict]:
    q = (query or "").strip()
    if not q:
        return []

    escaped = _escape_like(q)
    prefix = f"{escaped}%"
    rows = db.scalars(
        select(TickerDirectory)
        .where(
            or_(
                TickerDirectory.symbol.ilike(prefix, escape="\\"),
                TickerDirectory.name.ilike(f"%{escaped}%", escape="\\"),
            )
        )
        # Symbol-prefix matches first (typing "AAP" surfaces AAPL ahead of a name-only hit),
        # then shorter symbols (the plain ticker before its warrants/units), then alphabetical.
        .order_by(
            TickerDirectory.symbol.ilike(prefix, escape="\\").desc(),
            func.char_length(TickerDirectory.symbol),
            TickerDirectory.symbol,
        )
        .limit(limit)
    ).all()
    return [_to_dict(row) for row in rows]


def refresh_directory(db: Session) -> dict:
    """Weekly bulk refresh from Finnhub's symbol listing. Rate-limited/circuit-broken like
    every other provider call, and logs a job_runs row on every path (NFR-4). Never raises --
    a failed or skipped refresh just leaves the previous directory in place and retries next
    cycle, exactly like refresh_service.refresh_entry.
    """
    if not settings.finnhub_api_key:
        return _log_skip(db, "FINNHUB_API_KEY not configured")

    name = ProviderName.finnhub
    if not circuit_breaker.is_available(db, name):
        return _log_skip(db, "finnhub: circuit open")
    if not rate_limiter.allow(db, name):
        return _log_skip(db, "finnhub: rate limit budget exhausted")

    client = FinnhubClient(settings.finnhub_api_key)
    try:
        symbols = client.list_symbols()
    except Exception as exc:  # noqa: BLE001 -- best-effort job, never crash the caller
        rate_limiter.record_call(db, name, CallStatus.failure)
        db.add(JobRun(job_name=_JOB_NAME, status=JobStatus.failure, error_message=str(exc)))
        db.commit()
        return {"status": "failed", "upserted": 0}

    rate_limiter.record_call(db, name, CallStatus.success)
    upserted = _bulk_upsert(db, symbols)
    db.add(JobRun(job_name=_JOB_NAME, status=JobStatus.success))
    db.commit()
    return {"status": "ok", "upserted": upserted}


def _log_skip(db: Session, reason: str) -> dict:
    db.add(JobRun(job_name=_JOB_NAME, status=JobStatus.skipped, error_message=reason))
    db.commit()
    return {"status": "skipped", "upserted": 0}


def _bulk_upsert(db: Session, symbols: list[dict]) -> int:
    """Chunked ON CONFLICT(symbol) upsert. Deduped by symbol first because a single INSERT
    can't touch the same conflict target twice ("ON CONFLICT DO UPDATE command cannot affect
    row a second time") -- the Finnhub dump can list one symbol under more than one MIC.
    """
    deduped = _dedupe_by_symbol(symbols)
    total = 0
    for start in range(0, len(deduped), _UPSERT_CHUNK_SIZE):
        chunk = deduped[start : start + _UPSERT_CHUNK_SIZE]
        stmt = pg_insert(TickerDirectory).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[TickerDirectory.symbol],
            set_={
                "name": stmt.excluded.name,
                "exchange": stmt.excluded.exchange,
                "security_type": stmt.excluded.security_type,
                "updated_at": func.now(),
            },
        )
        db.execute(stmt)
        total += len(chunk)
    return total


def _dedupe_by_symbol(symbols: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in symbols:
        symbol = item["symbol"]
        if symbol in seen:
            continue
        seen.add(symbol)
        out.append(item)
    return out


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_dict(row: TickerDirectory) -> dict:
    return {
        "symbol": row.symbol,
        "name": row.name,
        "exchange": row.exchange,
        "security_type": row.security_type,
    }
