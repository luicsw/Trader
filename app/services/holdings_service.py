"""Personal position tracking (Post-Phase-5 addition). Deliberately narrow per the user's
explicit decision: shares + cost basis per share only -- not tax-lot accounting, not
realized-gains reporting, not cross-brokerage import. One row per company; upserting an
existing holding overwrites it rather than accumulating lots.

lookup_service/watchlist_service are imported lazily inside upsert() rather than at module
level -- wiki_service.assemble() (see get_for_company()) needs holding data on the same read
path the AI prompt builder uses, but wiki_service is itself imported by lookup_service and
watchlist_service, so a module-level import here would create an import cycle.
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, Holding, Watchlist
from app.services import ingest_service, sector_taxonomy


def _serialize(db: Session, holding: Holding) -> dict:
    company = holding.company
    latest_bar = ingest_service.latest_bar(db, company.id)
    latest_close = float(latest_bar.close) if latest_bar and latest_bar.close is not None else None

    shares = float(holding.shares)
    cost_basis_per_share = float(holding.cost_basis_per_share)
    cost_basis_total = cost_basis_per_share * shares
    market_value = latest_close * shares if latest_close is not None else None
    unrealized_gain = (market_value - cost_basis_total) if market_value is not None else None
    unrealized_gain_pct = (
        (unrealized_gain / cost_basis_total * 100) if unrealized_gain is not None and cost_basis_total else None
    )

    return {
        "ticker": company.ticker,
        "name": company.name,
        "category": sector_taxonomy.categorize(company.sector),
        "shares": shares,
        "cost_basis_per_share": cost_basis_per_share,
        "acquired_at": holding.acquired_at.isoformat() if holding.acquired_at else None,
        "notes": holding.notes,
        "latest_price": latest_close,
        "market_value": market_value,
        "cost_basis_total": cost_basis_total,
        "unrealized_gain": unrealized_gain,
        "unrealized_gain_pct": unrealized_gain_pct,
    }


def list_holdings(db: Session) -> list[dict]:
    holdings = db.scalars(select(Holding)).all()
    return [_serialize(db, holding) for holding in holdings]


def get_for_company(db: Session, company_id: int) -> dict | None:
    """Attaches position data to wiki_service.assemble()'s output -- the same read path the
    wiki page and the AI prompt builder both use, so the AI never sees a position the user
    can't also see on their own wiki page.
    """
    holding = db.scalar(select(Holding).where(Holding.company_id == company_id))
    if holding is None:
        return None
    return _serialize(db, holding)


def upsert(
    db: Session,
    ticker: str,
    shares: float,
    cost_basis_per_share: float,
    acquired_at: datetime | None = None,
    notes: str | None = None,
) -> dict:
    from app.services import lookup_service, watchlist_service

    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        lookup_service.get_or_fetch(db, ticker)
        company = db.scalar(select(Company).where(Company.ticker == ticker))

    # Auto-promote to watchlist (task's own scope decision) -- only when not already
    # tracked, so re-editing an existing holding's notes doesn't re-trigger a live provider
    # fetch every time (promote() isn't due-checked, unlike refresh_watchlist()).
    watchlist_entry = db.scalar(select(Watchlist).where(Watchlist.company_id == company.id))
    if watchlist_entry is None or not watchlist_entry.active:
        watchlist_service.promote(db, ticker)

    holding = db.scalar(select(Holding).where(Holding.company_id == company.id))
    if holding is None:
        holding = Holding(company_id=company.id, shares=shares, cost_basis_per_share=cost_basis_per_share)
        db.add(holding)
    holding.shares = shares
    holding.cost_basis_per_share = cost_basis_per_share
    holding.acquired_at = acquired_at
    holding.notes = notes
    db.commit()
    db.refresh(holding)
    return _serialize(db, holding)


def remove(db: Session, ticker: str) -> None:
    """Idempotent no-op if `ticker` has no holding. Leaves the watchlist entry untouched --
    removing a position tracked here is a separate concern from un-watchlisting a ticker.
    """
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        return

    holding = db.scalar(select(Holding).where(Holding.company_id == company.id))
    if holding is not None:
        db.delete(holding)
        db.commit()
