"""news_articles table

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-03

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sentiment = sa.Enum("positive", "neutral", "negative", name="sentiment")

    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("headline", sa.String(), nullable=False),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sentiment", sentiment, nullable=True),
    )
    op.create_unique_constraint("uq_news_article_company_url", "news_articles", ["company_id", "url"])
    op.create_index(
        "ix_news_article_company_published_at", "news_articles", ["company_id", "published_at"]
    )


def downgrade() -> None:
    op.drop_table("news_articles")
    sa.Enum(name="sentiment").drop(op.get_bind(), checkfirst=True)
