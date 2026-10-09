"""Initialize the default library once so removed libraries stay removed."""

from alembic import op

revision = "0007_removable_libraries"
down_revision = "0006_cover_only"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "INSERT INTO product_folders (path) SELECT '@library' "
        "WHERE NOT EXISTS (SELECT 1 FROM product_folders)"
    )
    for table in ("movies", "scrape_jobs"):
        op.execute(
            f"UPDATE {table} SET product_folder_id = "
            "(SELECT id FROM product_folders ORDER BY id LIMIT 1) "
            "WHERE product_folder_id IS NULL"
        )


def downgrade():
    pass  # No schema change or user data to undo.
