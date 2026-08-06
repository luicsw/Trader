"""add 'groq' to providername enum

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-06

Second AI provider (Post-Phase-5 Addition #2), shipped DORMANT -- no API key obtainable as of
2026-08-05. This is the exact bug class Phase 4 hit with 'gemini': the Python enum member was
added, the Postgres ALTER TYPE was forgotten, and the first rate-limiter check died on
`invalid input value for enum providername` (fixed by migration 0006). The rate limiter,
circuit breaker, and provider_call_log writer all key off this enum, so no Groq call can
succeed until both halves exist. Ships even though nothing uses it yet -- an unused enum value
costs nothing, and deferring it is precisely how the 0006 bug happened.
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE providername ADD VALUE IF NOT EXISTS 'groq'")


def downgrade() -> None:
    # Postgres has no direct "DROP VALUE" for enum types -- removing one requires recreating
    # the type and remapping every dependent column. Left as a no-op, exactly like 0006's
    # 'gemini' addition: additive-only, and a downgrade of the dormant Groq feature wouldn't
    # leave any 'groq' provider_call_log rows behind anyway (nothing writes them without a key).
    pass
