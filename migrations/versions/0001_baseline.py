"""baseline: schema as of the first self-hosted release

Revision ID: 0001
Revises: 
Create Date: 2026-10-11 09:06:17.482905

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():

    op.create_table('flowchart',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('flowchart_id', sa.String(length=36), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('json_data', sa.Text(), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('image_data_url', sa.Text(), nullable=True),
    sa.Column('image_mime', sa.String(length=64), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('is_published', sa.Boolean(), nullable=False),
    sa.Column('public_slug', sa.String(length=64), nullable=True),
    sa.Column('published_at', sa.DateTime(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('short_alt', sa.Text(), nullable=True),
    sa.Column('visibility', sa.String(length=16), nullable=False),
    sa.Column('flowchart_type', sa.String(length=16), nullable=False),
    sa.Column('deleted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('flowchart_id'),
    sa.UniqueConstraint('public_slug')
    )
    op.create_table('jobs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=True),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_jobs_owner_id'), ['owner_id'], unique=False)

    op.create_table('long_descriptions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('owner_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('alt_text', sa.Text(), nullable=False),
    sa.Column('long_markdown', sa.Text(), nullable=False),
    sa.Column('image_data_url', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_table('study_accounts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('study_code', sa.String(length=32), nullable=False),
    sa.Column('study_name', sa.String(length=128), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('study_accounts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_study_accounts_study_code'), ['study_code'], unique=True)
        batch_op.create_index(batch_op.f('ix_study_accounts_study_name'), ['study_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_study_accounts_user_id'), ['user_id'], unique=True)

    op.create_table('study_sessions',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('study_account_id', sa.String(length=36), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('study_name', sa.String(length=128), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('last_activity_at', sa.DateTime(), nullable=False),
    sa.Column('ended_at', sa.DateTime(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['study_account_id'], ['study_accounts.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('study_sessions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_study_sessions_study_account_id'), ['study_account_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_study_sessions_study_name'), ['study_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_study_sessions_user_id'), ['user_id'], unique=False)

    op.create_table('artifact_snapshots',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('study_session_id', sa.String(length=36), nullable=False),
    sa.Column('flowchart_id', sa.String(length=36), nullable=False),
    sa.Column('snapshot_type', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('image_data_url', sa.Text(), nullable=True),
    sa.Column('image_mime', sa.String(length=64), nullable=True),
    sa.Column('json_data', sa.JSON(), nullable=True),
    sa.Column('short_alt', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('public_slug', sa.String(length=64), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['study_session_id'], ['study_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('artifact_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_artifact_snapshots_flowchart_id'), ['flowchart_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_artifact_snapshots_snapshot_type'), ['snapshot_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_artifact_snapshots_study_session_id'), ['study_session_id'], unique=False)

    op.create_table('research_events',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('study_session_id', sa.String(length=36), nullable=False),
    sa.Column('flowchart_id', sa.String(length=36), nullable=True),
    sa.Column('artifact_snapshot_id', sa.String(length=36), nullable=True),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('event_category', sa.String(length=64), nullable=False),
    sa.Column('editor_mode', sa.String(length=64), nullable=True),
    sa.Column('representation_type', sa.String(length=64), nullable=True),
    sa.Column('success', sa.Boolean(), nullable=True),
    sa.Column('error_code', sa.String(length=128), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('event_data', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['study_session_id'], ['study_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('research_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_research_events_artifact_snapshot_id'), ['artifact_snapshot_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_research_events_event_category'), ['event_category'], unique=False)
        batch_op.create_index(batch_op.f('ix_research_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_research_events_flowchart_id'), ['flowchart_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_research_events_study_session_id'), ['study_session_id'], unique=False)




def downgrade():

    with op.batch_alter_table('research_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_research_events_study_session_id'))
        batch_op.drop_index(batch_op.f('ix_research_events_flowchart_id'))
        batch_op.drop_index(batch_op.f('ix_research_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_research_events_event_category'))
        batch_op.drop_index(batch_op.f('ix_research_events_artifact_snapshot_id'))

    op.drop_table('research_events')
    with op.batch_alter_table('artifact_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_artifact_snapshots_study_session_id'))
        batch_op.drop_index(batch_op.f('ix_artifact_snapshots_snapshot_type'))
        batch_op.drop_index(batch_op.f('ix_artifact_snapshots_flowchart_id'))

    op.drop_table('artifact_snapshots')
    with op.batch_alter_table('study_sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_study_sessions_user_id'))
        batch_op.drop_index(batch_op.f('ix_study_sessions_study_name'))
        batch_op.drop_index(batch_op.f('ix_study_sessions_study_account_id'))

    op.drop_table('study_sessions')
    with op.batch_alter_table('study_accounts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_study_accounts_user_id'))
        batch_op.drop_index(batch_op.f('ix_study_accounts_study_name'))
        batch_op.drop_index(batch_op.f('ix_study_accounts_study_code'))

    op.drop_table('study_accounts')
    op.drop_table('long_descriptions')
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_jobs_owner_id'))

    op.drop_table('jobs')
    op.drop_table('flowchart')

