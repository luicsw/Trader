"""price_forecasts table

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-06

Multi-horizon (30/60/90/180/360-day) expected low/high forecast rows from the second AI
provider (Groq), append-only like ai_analyses (spec.md FR-31). Ships DORMANT: nothing writes
here until GROQ_API_KEY is set. Separate migration from 0011's enum addition -- this table has
no providername column, so there's no "can't use a new enum value in the same transaction it
was added" concern; keeping them split just mirrors 0005/0006's shape.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_forecasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("expected_low", sa.Float(), nullable=False),
        sa.Column("expected_high", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False, server_default="on_demand"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_price_forecasts_company_generated_at",
        "price_forecasts",
        ["company_id", "generated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_forecasts_company_generated_at", table_name="price_forecasts")
    op.drop_table("price_forecasts")
