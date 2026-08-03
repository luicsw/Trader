"""watchlist, provider_call_log, job_runs tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("refresh_interval_minutes", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("last_scheduled_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scheduled_analysis_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_watchlist_company", "watchlist", ["company_id"])

    provider_name = sa.Enum("finnhub", "alpha_vantage", name="providername")
    call_status = sa.Enum("success", "failure", name="callstatus")
    op.create_table(
        "provider_call_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", provider_name, nullable=False),
        sa.Column("status", call_status, nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_provider_call_log_provider_called_at", "provider_call_log", ["provider", "called_at"]
    )

    job_status = sa.Enum("success", "failure", "skipped", name="jobstatus")
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_job_runs_job_name_started_at", "job_runs", ["job_name", "started_at"])


def downgrade() -> None:
    op.drop_table("job_runs")
    sa.Enum(name="jobstatus").drop(op.get_bind(), checkfirst=True)

    op.drop_table("provider_call_log")
    sa.Enum(name="callstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="providername").drop(op.get_bind(), checkfirst=True)

    op.drop_table("watchlist")
