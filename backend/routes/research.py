# backend/routes/research.py

from flask import Blueprint, request, jsonify
from backend.db import db
from backend.study.logging import log_research_event

research_bp = Blueprint("research", __name__)


@research_bp.route("/research-events", methods=["POST"])
def create_research_event():
    data = request.get_json() or {}

    event = log_research_event(
        study_account_id=data["study_account_id"],
        study_session_id=data.get("study_session_id"),
        flowchart_id=data.get("flowchart_id"),
        artifact_snapshot_id=data.get("artifact_snapshot_id"),
        event_type=data["event_type"],
        editor_mode=data.get("editor_mode"),
        representation_type=data.get("representation_type"),
        success=data.get("success"),
        error_code=data.get("error_code"),
        error_message=data.get("error_message"),
        event_data=data.get("event_data"),
    )

    db.session.commit()

    return jsonify({
        "ok": True,
        "research_event_id": event.id
    }), 201