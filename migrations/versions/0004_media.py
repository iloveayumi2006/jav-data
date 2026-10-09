"""Persistent media download queue."""

import sqlalchemy as sa
from alembic import op

revision = "0004_media"
down_revision = "0003_scrape_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("movie_id", sa.Integer(), sa.ForeignKey("movies.id"), nullable=False),
        *[
            sa.Column(name, sa.Text(), nullable=nullable)
            for name, nullable in (
                ("filename", False),
                ("url", True),
                ("referer", True),
                ("error", True),
            )
        ],
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("downloaded_bytes", sa.Integer(), nullable=False),
        sa.Column("total_bytes", sa.Integer()),
        sa.Column("requested_height", sa.Integer()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("movie_id", "filename"),
    )
    op.create_index("ix_media_assets_movie_id", "media_assets", ["movie_id"])
    op.create_index("ix_media_assets_status", "media_assets", ["status"])


def downgrade():
    op.drop_index("ix_media_assets_status", "media_assets")
    op.drop_index("ix_media_assets_movie_id", "media_assets")
    op.drop_table("media_assets")
