"""chat_messages table

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    chatrole = sa.Enum("user", "assistant", name="chatrole")

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role", chatrole, nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_messages")
    sa.Enum(name="chatrole").drop(op.get_bind(), checkfirst=True)
