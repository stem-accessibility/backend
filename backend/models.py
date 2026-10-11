from backend.db import db
import datetime
import uuid
from sqlalchemy.dialects.postgresql import UUID, JSONB

class Flowchart(db.Model):
    __tablename__ = "flowchart"
    id = db.Column(db.Integer, primary_key=True)
    flowchart_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID
    owner_id = db.Column(db.String(64), nullable=False)
    json_data = db.Column(db.Text, nullable=False)  # JSON data as text
    summary = db.Column(db.Text, nullable=True)  # Summary text
    
    image_data_url = db.Column(db.Text)  # "data:image/png;base64,...."
    image_mime = db.Column(db.String(64))  # e.g., "image/png"
    version = db.Column(db.Integer, nullable=False, default=1)
    is_published = db.Column(db.Boolean, nullable=False, default=False)
    public_slug = db.Column(db.String(64), unique=True, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    # NEW: metadata + repo visibility
    title = db.Column(db.Text, nullable=True)
    short_alt = db.Column(db.Text, nullable=True)
    # "visibility" = whether it appears in the open repository listing
    # (independent of permalink publishing)
    visibility = db.Column(db.String(16), nullable=False, default="private")
    flowchart_type = db.Column(db.String(16), nullable=False, default="unknown")

    # Soft delete
    deleted_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class LongDescription(db.Model):
    __tablename__ = "long_descriptions"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)  # permalink id
    
    owner_id = db.Column(db.String(64), nullable=False)  # Supabase user id
    
    title = db.Column(db.String(255), nullable=True) 
    alt_text = db.Column(db.Text, nullable=False)
    long_markdown = db.Column(db.Text, nullable=False)
    image_data_url = db.Column(db.Text, nullable=True)  # 🔹 NEW
                 # 🔹 NEW
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(64), nullable=False)  # e.g. "generate_summary"
    payload = db.Column(db.Text, nullable=False)     # JSON string
    status = db.Column(db.String(32), nullable=False, default="queued")  # queued|running|done|failed
    owner_id = db.Column(db.String(64), nullable=True, index=True)  # Supabase user id
    result = db.Column(db.Text, nullable=True)
    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

class StudyAccount(db.Model):
    __tablename__ = "study_accounts"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    study_code = db.Column(db.String(32), unique=True, nullable=False, index=True)
    study_name = db.Column(db.String(128), nullable=False, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)


class StudySession(db.Model):
    __tablename__ = "study_sessions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    study_account_id = db.Column(
        db.String(36),
        db.ForeignKey("study_accounts.id"),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.String(64), nullable=False, index=True)
    study_name = db.Column(db.String(128), nullable=False, index=True)
    started_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    last_activity_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)
    ended_at = db.Column(db.DateTime, nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)


class ArtifactSnapshot(db.Model):
    __tablename__ = "artifact_snapshots"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    study_session_id = db.Column(
        db.String(36),
        db.ForeignKey("study_sessions.id"),
        nullable=False,
        index=True,
    )
    flowchart_id = db.Column(db.String(36), nullable=False, index=True)
    snapshot_type = db.Column(db.String(64), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)

    file_name = db.Column(db.String(255), nullable=True)
    image_data_url = db.Column(db.Text, nullable=True)
    image_mime = db.Column(db.String(64), nullable=True)

    json_data = db.Column(db.JSON, nullable=True)
    short_alt = db.Column(db.Text, nullable=True)
    summary = db.Column(db.Text, nullable=True)
    title = db.Column(db.Text, nullable=True)
    public_slug = db.Column(db.String(64), nullable=True)
    metadata_json = db.Column(db.JSON, nullable=True)

# backend/models/research_event.py




class ResearchEvent(db.Model):
    __tablename__ = "research_events"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    study_session_id = db.Column(
        db.String(36),
        db.ForeignKey("study_sessions.id"),
        nullable=False,
        index=True,
    )

    flowchart_id = db.Column(db.String(36), nullable=True, index=True)
    artifact_snapshot_id = db.Column(db.String(36), nullable=True, index=True)

    event_type = db.Column(db.String(64), nullable=False, index=True)
    event_category = db.Column(db.String(64), nullable=False, index=True)

    editor_mode = db.Column(db.String(64), nullable=True)
    representation_type = db.Column(db.String(64), nullable=True)

    success = db.Column(db.Boolean, nullable=True)
    error_code = db.Column(db.String(128), nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    event_data = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.datetime.utcnow)