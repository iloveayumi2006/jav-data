"""Remove obsolete media rows and trailer-resolution tracking."""

import sqlalchemy as sa
from alembic import op

revision = "0006_cover_only"
down_revision = "0005_product_folders"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM media_assets WHERE kind != 'cover'")
    with op.batch_alter_table("media_assets") as batch:
        batch.drop_column("requested_height")


def downgrade():
    with op.batch_alter_table("media_assets") as batch:
        batch.add_column(sa.Column("requested_height", sa.Integer(), nullable=True))
