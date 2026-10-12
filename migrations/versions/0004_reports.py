"""reports: visitors can report a public page

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11

On Supabase the new table also gets row-level security with no policies, like the other backend
tables (the backend connects as the table owner and is unaffected).
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_slug", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_reports_public_slug", "reports", ["public_slug"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and bind.execute(
        sa.text("select 1 from information_schema.schemata where schema_name = 'auth'")
    ).scalar():
        op.execute("alter table reports enable row level security")


def downgrade():
    op.drop_index("ix_reports_public_slug", table_name="reports")
    op.drop_table("reports")
