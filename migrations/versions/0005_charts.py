"""charts: saved charts with a shareable link

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12

One table. A chart's data and settings are stored as JSON text, like flowchart.json_data.
On Supabase the new table also gets row-level security with no policies, like the other backend
tables (the backend connects as the table owner and is unaffected).
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "charts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chart_id", sa.String(36), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("dataset_json", sa.Text(), nullable=False),
        sa.Column("config_json", sa.Text(), nullable=False),
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visibility", sa.String(16), nullable=False, server_default="private"),
        sa.Column("public_slug", sa.String(64), nullable=True),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("chart_id", name="uq_charts_chart_id"),
        sa.UniqueConstraint("public_slug", name="uq_charts_public_slug"),
    )
    op.create_index("ix_charts_owner_id", "charts", ["owner_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql" and bind.execute(
        sa.text("select 1 from information_schema.schemata where schema_name = 'auth'")
    ).scalar():
        op.execute("alter table charts enable row level security")


def downgrade():
    op.drop_index("ix_charts_owner_id", table_name="charts")
    op.drop_table("charts")
