"""Template-based generation of wiki_sections bodies (spec.md T2.3) -- no AI call here,
just prose rendered from whatever raw data has been ingested so far. Rendering is split into
pure functions (no DB access) so they're unit-testable against plain dicts, with a thin
upsert wrapper doing the actual persistence.
"""
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.db.models import Company, PriceBar, WikiSection, WikiSectionKey

NOT_YET_INGESTED = {
    WikiSectionKey.financials_summary: (
        "No financial statement data has been ingested for this company yet."
    ),
    WikiSectionKey.news_digest: "No news has been ingested for this company yet.",
    WikiSectionKey.risks_notes: (
        "No specific risks have been identified yet -- this section is populated once "
        "financials and news coverage exist to reason over."
    ),
}


def render_overview(company: Company) -> str:
    if not company.name:
        return f"{company.ticker} -- profile data not yet available."

    parts = [company.name]
    if company.exchange:
        parts.append(f"trades on {company.exchange}")
    if company.sector:
        parts.append(f"in the {company.sector} sector")
    sentence = " ".join(parts) + "."

    if company.market_cap:
        sentence += f" Market capitalization is approximately {float(company.market_cap):,.0f}."

    return sentence


def render_key_metrics(company: Company, latest_bar: PriceBar | None) -> str:
    lines = []
    if latest_bar and latest_bar.close is not None:
        lines.append(f"Last close: {float(latest_bar.close):,.2f}")
    if latest_bar and latest_bar.high is not None and latest_bar.low is not None:
        lines.append(f"Day range: {float(latest_bar.low):,.2f} - {float(latest_bar.high):,.2f}")
    if company.market_cap:
        lines.append(f"Market cap: {float(company.market_cap):,.0f}")
    if company.sector:
        lines.append(f"Sector: {company.sector}")

    if not lines:
        return "No price or metric data available yet."
    return "\n".join(lines)


def render_sections(company: Company, latest_bar: PriceBar | None) -> dict[WikiSectionKey, str]:
    return {
        WikiSectionKey.overview: render_overview(company),
        WikiSectionKey.key_metrics: render_key_metrics(company, latest_bar),
        **NOT_YET_INGESTED,
    }


def generate_sections(db: Session, company: Company, latest_bar: PriceBar | None) -> None:
    """Upsert every wiki_sections row for `company` from currently-available data."""
    for section_key, body in render_sections(company, latest_bar).items():
        stmt = (
            pg_insert(WikiSection)
            .values(company_id=company.id, section_key=section_key, body=body)
            .on_conflict_do_update(
                index_elements=[WikiSection.company_id, WikiSection.section_key],
                set_={"body": body, "generated_at": func.now()},
            )
        )
        db.execute(stmt)
