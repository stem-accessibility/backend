"""long_descriptions.image_public: images on shared long descriptions are private by default

Rows that exist now are set to true so links people have already printed or embedded keep showing
their image; new rows default to false. Additive, and reversible by dropping the column.

Revision ID: b7d2e4f19a60
Revises: ee8798c827c8
Create Date: 2026-10-13

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7d2e4f19a60'
down_revision = 'ee8798c827c8'
branch_labels = None
depends_on = None


def upgrade():
    # Existing rows get true (their image is already public by design), then the default flips so
    # rows created from now on start private.
    op.add_column(
        'long_descriptions',
        sa.Column('image_public', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column('long_descriptions', 'image_public', server_default=sa.false())


def downgrade():
    op.drop_column('long_descriptions', 'image_public')
