"""Multiple product roots and clearable download history."""

import sqlalchemy as sa
from alembic import op

revision = "0005_product_folders"
down_revision = "0004_media"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "product_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
    )
    # Native nullable FK columns avoid rebuilding movies and disturbing existing cast/media.
    op.execute(
        "ALTER TABLE movies ADD COLUMN product_folder_id INTEGER REFERENCES product_folders(id)"
    )
    op.execute(
        "ALTER TABLE scrape_jobs ADD COLUMN product_folder_id INTEGER "
        "REFERENCES product_folders(id)"
    )
    op.add_column(
        "media_assets",
        sa.Column("history_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("media_assets", "history_hidden")
    op.execute("ALTER TABLE scrape_jobs DROP COLUMN product_folder_id")
    op.execute("ALTER TABLE movies DROP COLUMN product_folder_id")
    op.drop_table("product_folders")
