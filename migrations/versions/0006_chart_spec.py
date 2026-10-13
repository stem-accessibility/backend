"""charts: optional Vega-Lite specification

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12

Adds one nullable column, so existing rows are unaffected and need no backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("charts", sa.Column("spec_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("charts", "spec_json")
