"""supabase profiles table and row-level security

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-11

Supabase-only: skipped on plain Postgres / SQLite (no `auth` schema).

Supabase serves the public schema over its REST API to anyone holding the
publishable key, so every backend table gets RLS with no policies (denies the
anon/authenticated roles; the backend connects as the table owner and is
unaffected). `profiles` is written directly by the frontend at sign-up.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

BACKEND_TABLES = [
    "flowchart",
    "jobs",
    "long_descriptions",
    "research_events",
    "study_accounts",
    "study_sessions",
    "artifact_snapshots",
    "alembic_version",
]


def _is_supabase(bind) -> bool:
    if bind.dialect.name != "postgresql":
        return False
    return bool(
        bind.execute(
            sa.text("select 1 from information_schema.schemata where schema_name = 'auth'")
        ).scalar()
    )


def upgrade():
    bind = op.get_bind()
    if not _is_supabase(bind):
        return

    op.execute(
        """
        create table if not exists profiles (
          id uuid primary key references auth.users(id) on delete cascade,
          full_name text,
          role text,
          use_case text,
          created_at timestamptz not null default now()
        )
        """
    )
    op.execute("alter table profiles enable row level security")
    for name, clause in [
        ("profiles_select_own", "for select using (auth.uid() = id)"),
        ("profiles_insert_own", "for insert with check (auth.uid() = id)"),
        ("profiles_update_own", "for update using (auth.uid() = id) with check (auth.uid() = id)"),
    ]:
        op.execute(f"drop policy if exists {name} on profiles")
        op.execute(f"create policy {name} on profiles {clause}")

    for table in BACKEND_TABLES:
        op.execute(f"alter table {table} enable row level security")


def downgrade():
    bind = op.get_bind()
    if not _is_supabase(bind):
        return
    for table in BACKEND_TABLES:
        op.execute(f"alter table {table} disable row level security")
    op.execute("drop table if exists profiles")
