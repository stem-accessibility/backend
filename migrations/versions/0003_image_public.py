"""image_public: whether the source image is shown on the public page

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-11

Before this, a published page always served its uploaded image. To keep every already-published
page looking the same, existing published rows are backfilled to image_public = true; new rows
default to false (owners opt in). Owners can switch it off per diagram afterwards.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "flowchart",
        sa.Column("image_public", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE flowchart SET image_public = TRUE WHERE is_published = TRUE")


def downgrade():
    op.drop_column("flowchart", "image_public")
