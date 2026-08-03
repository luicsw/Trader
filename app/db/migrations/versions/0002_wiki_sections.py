"""wiki_sections table

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    section_key = sa.Enum(
        "overview",
        "financials_summary",
        "news_digest",
        "key_metrics",
        "risks_notes",
        name="wikisectionkey",
    )

    op.create_table(
        "wiki_sections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("section_key", section_key, nullable=False),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_wiki_section_company_key", "wiki_sections", ["company_id", "section_key"]
    )


def downgrade() -> None:
    op.drop_table("wiki_sections")
    sa.Enum(name="wikisectionkey").drop(op.get_bind(), checkfirst=True)
