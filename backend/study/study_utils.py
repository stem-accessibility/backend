import datetime
from backend.models import StudySession, StudyAccount, ArtifactSnapshot, ResearchEvent
from backend.db import db

def get_active_study_account(user_id: str):
    if not user_id:
        return None

    return StudyAccount.query.filter_by(
        user_id=user_id,
        is_active=True
    ).first()




def create_study_session(study_account, user_id: str):
    now = datetime.datetime.utcnow()
    session = StudySession(
        study_account_id=study_account.id,
        user_id=user_id,
        study_name=study_account.study_name,
        started_at=now,
        last_activity_at=now,
        ended_at=None,
        metadata_json=None,
    )
    db.session.add(session)
    db.session.commit()
    return session


def create_artifact_snapshot(
    study_session_id: str,
    flowchart_id: str,
    snapshot_type: str,
    file_name: str = None,
    image_data_url: str = None,
    image_mime: str = None,
    json_data=None,
    short_alt: str = None,
    summary: str = None,
    title: str = None,
    public_slug: str = None,
    metadata_json=None,
):
    snapshot = ArtifactSnapshot(
        study_session_id=study_session_id,
        flowchart_id=flowchart_id,
        snapshot_type=snapshot_type,
        created_at=datetime.datetime.utcnow(),
        file_name=file_name,
        image_data_url=image_data_url,
        image_mime=image_mime,
        json_data=json_data,
        short_alt=short_alt,
        summary=summary,
        title=title,
        public_slug=public_slug,
        metadata_json=metadata_json,
    )
    db.session.add(snapshot)
    db.session.commit()
    return snapshot

def get_latest_study_session(study_account_id: str):
    return (
        StudySession.query
        .filter_by(study_account_id=study_account_id)
        .order_by(StudySession.last_activity_at.desc())
        .first()
    )

def get_or_create_active_study_session(study_account, user_id: str, timeout_minutes: int = 30):
    now = datetime.datetime.utcnow()
    latest = get_latest_study_session(study_account.id)

    if latest:
        cutoff = now - datetime.timedelta(minutes=timeout_minutes)
        if latest.last_activity_at and latest.last_activity_at >= cutoff:
            return latest

    session = StudySession(
        study_account_id=study_account.id,
        user_id=user_id,
        study_name=study_account.study_name,
        started_at=now,
        last_activity_at=now,
        ended_at=None,
        metadata_json=None,
    )
    db.session.add(session)
    db.session.commit()
    return session

def touch_study_session(study_session):
    study_session.last_activity_at = datetime.datetime.utcnow()
    db.session.commit()
    return study_session

def create_research_event(
    study_session_id: str,
    event_type: str,
    event_category: str,
    flowchart_id: str = None,
    artifact_snapshot_id: str = None,
    editor_mode: str = None,
    representation_type: str = None,
    success: bool = None,
    error_code: str = None,
    error_message: str = None,
    event_data=None,
):
    event = ResearchEvent(
        study_session_id=study_session_id,
        flowchart_id=flowchart_id,
        artifact_snapshot_id=artifact_snapshot_id,
        event_type=event_type,
        event_category=event_category,
        editor_mode=editor_mode,
        representation_type=representation_type,
        success=success,
        error_code=error_code,
        error_message=error_message,
        event_data=event_data,
        created_at=datetime.datetime.utcnow(),
    )
    db.session.add(event)
    db.session.commit()
    return event