import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.session import Base


class CoverageTier(str, enum.Enum):
    watchlist = "watchlist"
    lookup = "lookup"


class WikiSectionKey(str, enum.Enum):
    overview = "overview"
    financials_summary = "financials_summary"
    news_digest = "news_digest"
    key_metrics = "key_metrics"
    risks_notes = "risks_notes"


class ProviderName(str, enum.Enum):
    finnhub = "finnhub"
    alpha_vantage = "alpha_vantage"


class CallStatus(str, enum.Enum):
    success = "success"
    failure = "failure"


class JobStatus(str, enum.Enum):
    success = "success"
    failure = "failure"
    skipped = "skipped"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    exchange: Mapped[str | None] = mapped_column(String(32))
    sector: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String)
    logo_url: Mapped[str | None] = mapped_column(String(512))
    market_cap: Mapped[float | None] = mapped_column(Numeric)
    coverage_tier: Mapped[CoverageTier] = mapped_column(
        Enum(CoverageTier, name="coveragetier"), default=CoverageTier.lookup
    )
    last_profile_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    price_bars: Mapped[list["PriceBar"]] = relationship(back_populates="company")
    wiki_sections: Mapped[list["WikiSection"]] = relationship(back_populates="company")
    watchlist_entry: Mapped["Watchlist | None"] = relationship(back_populates="company")


class PriceBar(Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("company_id", "ts", "interval", name="uq_price_bar_company_ts_interval"),
        Index("ix_price_bar_company_interval_ts", "company_id", "interval", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval: Mapped[str] = mapped_column(String(8))
    open: Mapped[float | None] = mapped_column(Numeric)
    high: Mapped[float | None] = mapped_column(Numeric)
    low: Mapped[float | None] = mapped_column(Numeric)
    close: Mapped[float | None] = mapped_column(Numeric)
    volume: Mapped[int | None] = mapped_column(BigInteger)

    company: Mapped["Company"] = relationship(back_populates="price_bars")


class WikiSection(Base):
    __tablename__ = "wiki_sections"
    __table_args__ = (
        UniqueConstraint("company_id", "section_key", name="uq_wiki_section_company_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    section_key: Mapped[WikiSectionKey] = mapped_column(Enum(WikiSectionKey, name="wikisectionkey"))
    body: Mapped[str] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="wiki_sections")


class Watchlist(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("company_id", name="uq_watchlist_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    refresh_interval_minutes: Mapped[int] = mapped_column(Integer, default=20)
    last_scheduled_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scheduled_analysis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="watchlist_entry")


class ProviderCallLog(Base):
    __tablename__ = "provider_call_log"
    __table_args__ = (
        Index("ix_provider_call_log_provider_called_at", "provider", "called_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[ProviderName] = mapped_column(Enum(ProviderName, name="providername"))
    status: Mapped[CallStatus] = mapped_column(Enum(CallStatus, name="callstatus"))
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (
        Index("ix_job_runs_job_name_started_at", "job_name", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="jobstatus"))
    error_message: Mapped[str | None] = mapped_column(String)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
