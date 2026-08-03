import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
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
    gemini = "gemini"


class Sentiment(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class Verdict(str, enum.Enum):
    buy = "buy"
    hold = "hold"
    sell = "sell"


class AnalysisTrigger(str, enum.Enum):
    scheduled = "scheduled"
    on_demand = "on_demand"
    initial = "initial"


class CallStatus(str, enum.Enum):
    success = "success"
    failure = "failure"


class JobStatus(str, enum.Enum):
    success = "success"
    failure = "failure"
    skipped = "skipped"


class ChatRole(str, enum.Enum):
    user = "user"
    assistant = "assistant"


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
    news_articles: Mapped[list["NewsArticle"]] = relationship(back_populates="company")
    holding: Mapped["Holding | None"] = relationship(back_populates="company")


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


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("company_id", "url", name="uq_news_article_company_url"),
        Index("ix_news_article_company_published_at", "company_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    headline: Mapped[str] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(String)
    url: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sentiment: Mapped[Sentiment | None] = mapped_column(Enum(Sentiment, name="sentiment"))

    company: Mapped["Company"] = relationship(back_populates="news_articles")


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


class Holding(Base):
    """Personal position tracking (Post-Phase-5 addition) -- deliberately scoped to shares +
    cost basis only, not tax lots/realized-gains/cross-brokerage import (explicit user
    decision). One row per company: editing an existing holding overwrites it in place
    rather than accumulating lots.
    """

    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("company_id", name="uq_holding_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    shares: Mapped[float] = mapped_column(Numeric)
    cost_basis_per_share: Mapped[float] = mapped_column(Numeric)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="holding")


class ChatMessage(Base):
    """Grounded AI chat (Post-Phase-5 addition) -- linear, single-user history, no
    multi-conversation concept (spec.md's chat decision doesn't call for one). Append-only,
    same philosophy as ai_analyses: never edited, ordered strictly by created_at.
    """

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[ChatRole] = mapped_column(Enum(ChatRole, name="chatrole"))
    content: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class AiAnalysis(Base):
    """One row per verdict ever generated -- append-only, never overwritten (spec.md FR-15)."""

    __tablename__ = "ai_analyses"
    __table_args__ = (
        Index("ix_ai_analyses_company_generated_at", "company_id", "generated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    verdict: Mapped[Verdict] = mapped_column(Enum(Verdict, name="verdict"))
    confidence: Mapped[float] = mapped_column(Float)
    reasoning_text: Mapped[str] = mapped_column(String)
    price_targets: Mapped[dict] = mapped_column(JSONB)
    hold_period_days: Mapped[dict] = mapped_column(JSONB)
    cited_sources: Mapped[list] = mapped_column(JSONB)
    context_snapshot: Mapped[dict] = mapped_column(JSONB)
    trigger: Mapped[AnalysisTrigger] = mapped_column(Enum(AnalysisTrigger, name="analysistrigger"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship()
    critiques: Mapped[list["AiCritique"]] = relationship(back_populates="analysis")


class AiCritique(Base):
    """One row per second-opinion critique ever generated -- append-only, always on-demand
    (spec.md FR-18 to FR-20). One-to-many: an analysis can be critiqued more than once.
    """

    __tablename__ = "ai_critiques"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("ai_analyses.id"))
    agrees_with_verdict_direction: Mapped[bool] = mapped_column(Boolean)
    biggest_weakness: Mapped[str] = mapped_column(String)
    revised_price_targets: Mapped[dict] = mapped_column(JSONB)
    revised_confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(String)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analysis: Mapped["AiAnalysis"] = relationship(back_populates="critiques")


class VerdictOutcome(Base):
    """One row per evaluated verdict, at a fixed horizon -- append-only, never overwritten
    (same philosophy as ai_analyses/ai_critiques). Turns "the AI feels confident" into
    something checkable: did price actually move the way the verdict implied.
    """

    __tablename__ = "verdict_outcomes"
    __table_args__ = (UniqueConstraint("analysis_id", name="uq_verdict_outcome_analysis"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("ai_analyses.id"))
    horizon_days: Mapped[int] = mapped_column(Integer)
    price_at_verdict: Mapped[float] = mapped_column(Float)
    price_at_horizon: Mapped[float] = mapped_column(Float)
    price_change_pct: Mapped[float] = mapped_column(Float)
    directionally_correct: Mapped[bool] = mapped_column(Boolean)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analysis: Mapped["AiAnalysis"] = relationship()
