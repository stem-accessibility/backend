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
    # The original image lives in `stem_images` (see backend/image_store.py). `image_data_url`
    # above is the legacy inline copy: new rows leave it empty, and `flask migrate-images` moves
    # old rows over.
    image_id = db.Column(db.String(36), nullable=True, index=True)
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
    # Whether the uploaded source image is served on the public page (/p/<slug>/image).
    # Off by default: sharing a source image is a separate choice from sharing the page.
    image_public = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    # Soft delete
    deleted_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

class StemImage(db.Model):
    """The original uploaded image for a STEM image, kept apart from the rows people list and
    search so those stay small. Reached only through backend/image_store.py, so moving the bytes
    to object storage later changes one class and the `data` column, not the callers."""
    __tablename__ = "stem_images"
    id = db.Column(db.Integer, primary_key=True)
    image_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID, opaque
    owner_id = db.Column(db.String(64), nullable=False, index=True)
    mime = db.Column(db.String(64), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    data = db.Column(db.LargeBinary, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)


class LongDescription(db.Model):
    __tablename__ = "long_descriptions"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)  # permalink id
    
    owner_id = db.Column(db.String(64), nullable=False)  # Supabase user id
    
    title = db.Column(db.String(255), nullable=True) 
    alt_text = db.Column(db.Text, nullable=False)
    long_markdown = db.Column(db.Text, nullable=False)
    # Legacy inline copy. New rows keep the image in `stem_images` and set image_id instead;
    # `flask migrate-images` moves old rows over.
    image_data_url = db.Column(db.Text, nullable=True)
    image_id = db.Column(db.String(36), nullable=True, index=True)
    # Whether visitors to the shared page can see the image. Off by default, like
    # Flowchart.image_public; the owner always can. Rows that existed before this column keep
    # showing their image (the migration sets them to true), so printed links do not change.
    image_public = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
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

class Report(db.Model):
    """A visitor's report about a public page (spam, abuse, or content that should not be shared)."""
    __tablename__ = "reports"
    id = db.Column(db.Integer, primary_key=True)
    public_slug = db.Column(db.String(64), nullable=False, index=True)
    reason = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)


class Chart(db.Model):
    """A chart made on the Charts page: the uploaded table plus how it was mapped and labelled.

    The page rebuilds the table, navigable outline and sonification from these two JSON blobs, so
    nothing derived is stored. Sharing uses the same two flags as Flowchart (`is_published` and
    `visibility`) so apply_sharing / current_sharing work unchanged. There is no chart listing yet,
    so `visibility = "public"` is recorded but has no effect beyond what a link already does.
    """
    __tablename__ = "charts"
    id = db.Column(db.Integer, primary_key=True)
    chart_id = db.Column(db.String(36), unique=True, nullable=False)  # UUID
    owner_id = db.Column(db.String(64), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=True)
    dataset_json = db.Column(db.Text, nullable=False)  # {"columns": [...], "rows": [...], "name": ...}
    config_json = db.Column(db.Text, nullable=False)   # whitelisted chart settings
    spec_json = db.Column(db.Text, nullable=True)      # optional Vega-Lite spec (see clean_spec)

    is_published = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    visibility = db.Column(db.String(16), nullable=False, default="private", server_default="private")
    public_slug = db.Column(db.String(64), unique=True, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)

    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False
    )
