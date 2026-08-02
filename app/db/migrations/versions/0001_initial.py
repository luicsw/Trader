"""initial schema -- companies, price_bars

Revision ID: 0001
Revises:
Create Date: 2026-08-02

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    coverage_tier = sa.Enum("watchlist", "lookup", name="coveragetier")

    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("exchange", sa.String(length=32), nullable=True),
        sa.Column("sector", sa.String(length=128), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("logo_url", sa.String(length=512), nullable=True),
        sa.Column("market_cap", sa.Numeric(), nullable=True),
        sa.Column("coverage_tier", coverage_tier, nullable=False, server_default="lookup"),
        sa.Column("last_profile_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_companies_ticker", "companies", ["ticker"])
    op.create_index("ix_companies_ticker", "companies", ["ticker"])

    op.create_table(
        "price_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval", sa.String(length=8), nullable=False),
        sa.Column("open", sa.Numeric(), nullable=True),
        sa.Column("high", sa.Numeric(), nullable=True),
        sa.Column("low", sa.Numeric(), nullable=True),
        sa.Column("close", sa.Numeric(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_price_bar_company_ts_interval", "price_bars", ["company_id", "ts", "interval"]
    )
    op.create_index(
        "ix_price_bar_company_interval_ts", "price_bars", ["company_id", "interval", "ts"]
    )


def downgrade() -> None:
    op.drop_table("price_bars")
    op.drop_table("companies")
    sa.Enum(name="coveragetier").drop(op.get_bind(), checkfirst=True)
