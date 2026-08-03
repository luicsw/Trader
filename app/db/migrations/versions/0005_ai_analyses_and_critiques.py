"""ai_analyses, ai_critiques tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    verdict = sa.Enum("buy", "hold", "sell", name="verdict")
    trigger = sa.Enum("scheduled", "on_demand", "initial", name="analysistrigger")

    op.create_table(
        "ai_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("verdict", verdict, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reasoning_text", sa.String(), nullable=False),
        sa.Column("price_targets", JSONB(), nullable=False),
        sa.Column("hold_period_days", JSONB(), nullable=False),
        sa.Column("cited_sources", JSONB(), nullable=False),
        sa.Column("context_snapshot", JSONB(), nullable=False),
        sa.Column("trigger", trigger, nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ai_analyses_company_generated_at", "ai_analyses", ["company_id", "generated_at"]
    )

    op.create_table(
        "ai_critiques",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("ai_analyses.id"), nullable=False),
        sa.Column("agrees_with_verdict_direction", sa.Boolean(), nullable=False),
        sa.Column("biggest_weakness", sa.String(), nullable=False),
        sa.Column("revised_price_targets", JSONB(), nullable=False),
        sa.Column("revised_confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("ai_critiques")
    op.drop_table("ai_analyses")
    sa.Enum(name="analysistrigger").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="verdict").drop(op.get_bind(), checkfirst=True)
