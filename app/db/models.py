import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
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
