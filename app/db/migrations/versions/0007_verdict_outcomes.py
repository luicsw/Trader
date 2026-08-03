"""verdict_outcomes table

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "verdict_outcomes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("analysis_id", sa.Integer(), sa.ForeignKey("ai_analyses.id"), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("price_at_verdict", sa.Float(), nullable=False),
        sa.Column("price_at_horizon", sa.Float(), nullable=False),
        sa.Column("price_change_pct", sa.Float(), nullable=False),
        sa.Column("directionally_correct", sa.Boolean(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_verdict_outcome_analysis", "verdict_outcomes", ["analysis_id"]
    )


def downgrade() -> None:
    op.drop_table("verdict_outcomes")
