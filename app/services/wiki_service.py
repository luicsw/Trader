"""wiki_service.assemble(ticker) -- the single read path for a company's wiki page
(spec.md FR-10). Reads only from Postgres; used by both the wiki API route and, later,
the AI prompt builder, so the AI can never see data the user can't also see.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Company, PriceBar, WikiSection


def assemble(db: Session, ticker: str) -> dict | None:
    ticker = ticker.upper()
    company = db.scalar(select(Company).where(Company.ticker == ticker))
    if company is None:
        return None

    latest_bar = db.scalar(
        select(PriceBar)
        .where(PriceBar.company_id == company.id)
        .order_by(PriceBar.ts.desc())
        .limit(1)
    )
    sections = db.scalars(
        select(WikiSection).where(WikiSection.company_id == company.id)
    ).all()

    return {
        "ticker": company.ticker,
        "name": company.name,
        "exchange": company.exchange,
        "sector": company.sector,
        "description": company.description,
        "logo_url": company.logo_url,
        "market_cap": float(company.market_cap) if company.market_cap is not None else None,
        "coverage_tier": company.coverage_tier.value,
        "last_updated": company.last_profile_refresh_at.isoformat()
        if company.last_profile_refresh_at
        else None,
        "latest_price": {
            "open": float(latest_bar.open) if latest_bar and latest_bar.open is not None else None,
            "high": float(latest_bar.high) if latest_bar and latest_bar.high is not None else None,
            "low": float(latest_bar.low) if latest_bar and latest_bar.low is not None else None,
            "close": float(latest_bar.close) if latest_bar and latest_bar.close is not None else None,
            "ts": latest_bar.ts.isoformat() if latest_bar else None,
        }
        if latest_bar
        else None,
        "sections": {
            section.section_key.value: {
                "body": section.body,
                "generated_at": section.generated_at.isoformat(),
            }
            for section in sections
        },
    }
