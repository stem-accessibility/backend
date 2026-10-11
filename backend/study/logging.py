from backend.db import db
from backend.models import ResearchEvent
from backend.study.event_types import EVENT_TYPES


def log_research_event(
    *,
    study_account_id,
    event_type,
    study_session_id=None,
    flowchart_id=None,
    artifact_snapshot_id=None,
    editor_mode=None,
    representation_type=None,
    success=None,
    error_code=None,
    error_message=None,
    event_data=None,
):
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unknown event_type: {event_type}")

    event = ResearchEvent(
        study_account_id=study_account_id,
        study_session_id=study_session_id,
        flowchart_id=flowchart_id,
        artifact_snapshot_id=artifact_snapshot_id,
        event_type=event_type,
        event_category=EVENT_TYPES[event_type],
        editor_mode=editor_mode,
        representation_type=representation_type,
        success=success,
        error_code=error_code,
        error_message=error_message,
        event_data=event_data or {},
    )

    db.session.add(event)
    return event