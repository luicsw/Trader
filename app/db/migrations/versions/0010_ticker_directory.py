"""ticker_directory table

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-05

Local cache of the tradable US symbol universe backing the Add Holding autocomplete
(spec.md FR-34). Plain ILIKE search on a single-user table -- no pg_trgm extension needed;
the UNIQUE index on `symbol` already serves prefix matches.
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ticker_directory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("exchange", sa.String(length=32), nullable=True),
        sa.Column("security_type", sa.String(length=64), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ticker_directory_symbol", "ticker_directory", ["symbol"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_ticker_directory_symbol", table_name="ticker_directory")
    op.drop_table("ticker_directory")
