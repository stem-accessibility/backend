"""Private slide decks and extracted diagram checkpoints."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "slide_decks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("pdf_data", sa.LargeBinary(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("pages_json", sa.Text(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_slide_decks_owner_id", "slide_decks", ["owner_id"])
    op.create_table(
        "deck_diagrams",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("deck_id", sa.String(36), sa.ForeignKey("slide_decks.id"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("box_json", sa.Text(), nullable=False),
        sa.Column("image_id", sa.String(36), nullable=False),
        sa.Column("flowchart_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("deck_id", "page_number", "position", name="uq_deck_region"),
    )
    op.create_index("ix_deck_diagrams_deck_id", "deck_diagrams", ["deck_id"])
    bind = op.get_bind()
    if (
        bind.dialect.name == "postgresql"
        and bind.execute(
            sa.text("select 1 from information_schema.schemata where schema_name = 'auth'")
        ).scalar()
    ):
        op.execute("alter table slide_decks enable row level security")
        op.execute("alter table deck_diagrams enable row level security")


def downgrade():
    op.drop_table("deck_diagrams")
    op.drop_table("slide_decks")
