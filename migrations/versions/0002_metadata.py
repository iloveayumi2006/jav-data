"""Movies, shared actress records, and ordered cast."""

import sqlalchemy as sa
from alembic import op

revision = "0002_metadata"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "movies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("distribution_product_id", sa.String(120, collation="NOCASE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        *[
            sa.Column(name, sa.Text())
            for name in (
                "manufacturer_product_id",
                "streaming_release_date",
                "product_release_date",
                "runtime",
                "series",
                "maker",
                "label",
                "video_intro",
                "source_url",
            )
        ],
        *[
            sa.Column(name, sa.JSON(), nullable=False)
            for name in (
                "directors",
                "genres",
                "related_tags",
            )
        ],
        sa.Column("scraped_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("distribution_product_id"),
    )
    op.create_table(
        "actresses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
    )
    op.create_table(
        "movie_actresses",
        sa.Column(
            "movie_id",
            sa.Integer(),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("actress_id", sa.Integer(), sa.ForeignKey("actresses.id"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("movie_actresses")
    op.drop_table("actresses")
    op.drop_table("movies")
