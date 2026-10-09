"""Persistent URL scraping queue."""

import sqlalchemy as sa
from alembic import op

revision = "0003_scrape_jobs"
down_revision = "0002_metadata"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scrape_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_scrape_jobs_status", "scrape_jobs", ["status"])


def downgrade():
    op.drop_index("ix_scrape_jobs_status", table_name="scrape_jobs")
    op.drop_table("scrape_jobs")
