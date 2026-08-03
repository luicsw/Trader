"""add 'gemini' to providername enum

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-03

"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providername ADD VALUE IF NOT EXISTS 'gemini'")


def downgrade() -> None:
    # Postgres has no direct "DROP VALUE" for enum types -- removing one requires recreating
    # the type and remapping every dependent column. Left as a no-op: additive-only, and a
    # downgrade of the Phase 4 AI pipeline wouldn't leave any 'gemini' rows behind anyway
    # once ai_analyses/provider_call_log rows referencing it are gone.
    pass
