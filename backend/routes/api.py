from flask import Flask, request, jsonify, Blueprint
from openai import OpenAI
from openai import RateLimitError, APIError, Timeout
from typing import Optional
import xml.etree.ElementTree as ET
import json
import re
import time
import os
import base64    
import traceback
from backend.db import db
from dotenv import load_dotenv
from backend.mermaid_parser import parse_mermaid_flowchart_td
from backend.auth import optional_user, require_auth
from backend.guest import client_ip, is_guest_owner, limiter
from flask import g
import uuid
# Import models after initializing db to avoid circular imports
from backend.models import Flowchart, LongDescription
from backend.image_store import (
    ImageError,
    flowchart_image_data_url,
    set_flowchart_image,
)
from sqlalchemy import inspect, text
from backend.study.study_utils import get_active_study_account, create_artifact_snapshot, get_or_create_active_study_session, touch_study_session, create_research_event
from backend.study.event_types import EVENT_TYPES

from datetime import datetime
# Load environment variables from .env file (only in local/dev)





api_bp = Blueprint("api", __name__)

@api_bp.get("/")
def home():
    return "Hello, Render!", 200

# then move/define:
# @api_bp.route("/flowcharts"...)
# @api_bp.route("/publish/<flowchart_id>"...)
# @api_bp.route("/repo"...)
# etc.


def error(status: int, msg: str):
    return jsonify({"error": msg}), status

def extract_json_fenced(text: str) -> dict:
    """
    Extract JSON from a ```json fenced code block returned by a model.
    """
    import re
    m = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if not m:
        raise ValueError("No ```json fenced block found.")
    return json.loads(m.group(1))

SHARING_STATES = ("public", "link", "private")


def current_sharing(r: Flowchart) -> str:
    """
    The one setting people see: "public" (listed + has a link), "link" (has a link, not listed),
    or "private". Derived from the two stored flags, so a row that is marked public but was never
    published reads as "private" (which is what visitors actually get).
    """
    if not getattr(r, "is_published", False):
        return "private"
    return "public" if getattr(r, "visibility", "private") == "public" else "link"


def apply_sharing(r: Flowchart, sharing: str) -> None:
    """
    Set visibility + publication together so they cannot drift apart. The slug is kept when
    unpublishing, so re-sharing restores the same link.
    """
    if sharing not in SHARING_STATES:
        raise ValueError("sharing must be 'public', 'link', or 'private'")
    if sharing == "private":
        r.visibility = "private"
        r.is_published = False
        r.published_at = None
        return
    r.visibility = "public" if sharing == "public" else "private"
    if not r.public_slug:
        r.public_slug = uuid.uuid4().hex[:12]
    if not r.is_published:
        r.is_published = True
        r.published_at = datetime.utcnow()


def serialize_flowchart(r: Flowchart, include_json: bool = True, public_mode: bool = False):
    has_image = bool(getattr(r, "image_id", None) or getattr(r, "image_data_url", None))
    image_public = bool(getattr(r, "image_public", False))

    if public_mode:
        # Visitors only see the source image when the owner chose to share it.
        has_image = has_image and image_public
        image_endpoint = f"/p/{r.public_slug}/image" if (has_image and r.public_slug and r.is_published) else None
    else:
        image_endpoint = f"/get/{r.flowchart_id}/image" if has_image else None

    payload = {
        "flowchart_id": r.flowchart_id,
        "title": getattr(r, "title", None),
        "short_alt": getattr(r, "short_alt", None),
        "visibility": getattr(r, "visibility", "private"),
        "sharing": current_sharing(r),
        "image_public": image_public,
        "flowchart_type": getattr(r, "flowchart_type", "unknown"),
        "guest": is_guest_owner(getattr(r, "owner_id", None)),
        "summary": r.summary,
        "has_image": has_image,
        "image_mime": getattr(r, "image_mime", None),
        "image_endpoint": image_endpoint,
        "created_at": r.created_at.isoformat() if getattr(r, "created_at", None) else None,
        "version": getattr(r, "version", None),
        "is_published": bool(getattr(r, "is_published", False)),
        "public_slug": getattr(r, "public_slug", None),
        "published_at": r.published_at.isoformat() if getattr(r, "published_at", None) else None,
        "deleted_at": r.deleted_at.isoformat() if getattr(r, "deleted_at", None) else None,
    }
    if include_json:
        payload["json_data"] = json.loads(r.json_data) if r.json_data else None
    return payload

def get_owned_flowchart_or_404(flowchart_id: str) -> Flowchart:
    r = (
        Flowchart.query
        .filter_by(flowchart_id=flowchart_id, owner_id=g.user_id)
        .filter(Flowchart.deleted_at.is_(None))
        .first()
    )
    return r


# -------------------------
# Routes
# -------------------------

@api_bp.route("/whoami", methods=["GET"])
@require_auth
def whoami():
    return jsonify({"user_id": g.user_id, "email": g.user_email}), 200

# -------- Mermaid parsing --------
@api_bp.route('/parse-mermaid', methods=['POST'])
def parse_mermaid():
    try:
        payload = request.get_json(silent=True) or {}
        mermaid = payload.get('mermaid', '')

        if not isinstance(mermaid, str) or not mermaid.strip():
            return jsonify({'error': 'Missing mermaid string'}), 400

        parsed = parse_mermaid_flowchart_td(mermaid)
        return jsonify(parsed), 200

    except Exception as e:
        print("Error in /parse-mermaid:", traceback.format_exc())
        return jsonify({'error': f'Internal Server Error: {str(e)}'}), 500

# -------- Flowchart CRUD --------
@api_bp.route("/flowcharts", methods=["GET"])
@require_auth
def list_flowcharts():
    rows = (
        Flowchart.query
        .filter_by(owner_id=g.user_id)
        .filter(Flowchart.deleted_at.is_(None))
        .order_by(Flowchart.created_at.desc())
        .all()
    )
    return jsonify([serialize_flowchart(r, include_json=False) for r in rows]), 200

@api_bp.route("/flowcharts", methods=["POST"])
@require_auth
def create_flowchart():
    """
    Create a flowchart row.
    Required: json_data (dict/list), summary (str)
    Optional: flowchart_id, title, short_alt, sharing ("public" | "link" | "private"; default
    "private"), image_public, flowchart_type, image_data_url, image_mime.
    The older "visibility" field is still accepted ("public" -> sharing "public").
    """
    try:
        data = request.get_json(silent=True) or {}
        if data.get("sharing") is not None and data["sharing"] not in SHARING_STATES:
            return error(400, "sharing must be 'public', 'link', or 'private'")

        json_data = data.get("json_data")
        summary = data.get("summary")
        short_alt = data.get("short_alt")

        if json_data is None:
            return error(400, "Missing required field: json_data")

        if summary is not None and not isinstance(summary, str):
            return error(400, "summary must be a string")

        if short_alt is not None and not isinstance(short_alt, str):
            return error(400, "short_alt must be a string")

        flowchart_id = data.get("flowchart_id") or str(uuid.uuid4())

        existing = Flowchart.query.filter_by(flowchart_id=flowchart_id, owner_id=g.user_id).first()
        if existing:
            return error(400, "Flowchart with this ID already exists")

        r = Flowchart(
            flowchart_id=flowchart_id,
            owner_id=g.user_id,
            json_data=json.dumps(json_data),
            summary=summary,
            title=data.get("title"),
            short_alt=short_alt,
            flowchart_type=data.get("flowchart_type", "unknown"),
            image_public=bool(data.get("image_public", False)),
        )
        # The original goes to the image store (not the flowchart row); ImageError -> 400 below.
        set_flowchart_image(r, data.get("image_data_url"))
        # "sharing" is preferred; the older "visibility" field maps onto it.
        sharing = data.get("sharing")
        if sharing is None:
            sharing = "public" if data.get("visibility") == "public" else "private"
        apply_sharing(r, sharing)

        db.session.add(r)
        db.session.commit()
        study_account = get_active_study_account(r.owner_id)

        if study_account:
            study_session = get_or_create_active_study_session(study_account, r.owner_id)

            snapshot_type = "machine_draft" if r.summary else "initial_upload"

            snapshot = create_artifact_snapshot(
                study_session_id=study_session.id,
                flowchart_id=r.flowchart_id,
                snapshot_type=snapshot_type,
                image_data_url=flowchart_image_data_url(r),
                image_mime=r.image_mime,
                json_data=json.loads(r.json_data) if r.json_data else None,
                short_alt=r.short_alt,
                summary=r.summary,
                title=r.title,
                public_slug=r.public_slug,
            )
            touch_study_session(study_session)
            print("Created artifact snapshot:", snapshot.id)

       
        
        return jsonify(serialize_flowchart(r, include_json=False)), 201

    except ImageError as e:
        db.session.rollback()
        return error(400, str(e))
    except Exception as e:
        print("Error in POST /flowcharts:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))

@api_bp.route('/get/<flowchart_id>', methods=['GET'])
@require_auth
def get_flowchart(flowchart_id):
    try:
        r = get_owned_flowchart_or_404(flowchart_id)
        if not r:
            return error(404, "Flowchart not found")
        return jsonify(serialize_flowchart(r, include_json=True)), 200
    except Exception as e:
        print("Error in GET /get/<flowchart_id>:", traceback.format_exc())
        return error(500, str(e))

@api_bp.route('/get/<flowchart_id>/image', methods=['GET'])
@require_auth
def get_flowchart_image(flowchart_id):
    r = get_owned_flowchart_or_404(flowchart_id)
    url = flowchart_image_data_url(r) if r else None
    if not url:
        return error(404, "Image not found")
    return jsonify({"image_data_url": url, "image_mime": r.image_mime}), 200


@api_bp.route('/flowcharts/<flowchart_id>/image', methods=['DELETE'])
@require_auth
def delete_flowchart_image(flowchart_id):
    """Remove only the original image; the STEM image itself stays."""
    try:
        r = get_owned_flowchart_or_404(flowchart_id)
        if not r:
            return error(404, "Flowchart not found")
        set_flowchart_image(r, None)
        db.session.commit()
        return jsonify(serialize_flowchart(r, include_json=False)), 200
    except Exception as e:
        print("Error in DELETE /flowcharts/<flowchart_id>/image:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))


@api_bp.route('/flowcharts/<flowchart_id>', methods=['PUT'])
@require_auth
def update_flowchart(flowchart_id):
    """
    Update editable fields:
      - json_data, summary, title, short_alt, flowchart_type
      - image_data_url, image_mime
    NOTE: publishing + repo visibility have separate endpoints.
    """
    try:
        data = request.get_json(silent=True) or {}
        r = get_owned_flowchart_or_404(flowchart_id)

        had_summary_before = bool(r.summary and r.summary.strip())
        if not r:
            return error(404, "Flowchart not found")

        if "json_data" in data:
            jd = data["json_data"]
            if isinstance(jd, str):
                # validate
                json.loads(jd)
                r.json_data = jd
            else:
                r.json_data = json.dumps(jd)

        if "summary" in data:
            if data["summary"] is not None and not isinstance(data["summary"], str):
                return error(400, "summary must be a string")
            r.summary = data["summary"]

        for field in ["title", "short_alt", "flowchart_type"]:
            if field in data:
                setattr(r, field, data[field])

        if "image_data_url" in data:
            set_flowchart_image(r, data["image_data_url"])  # None removes it; ImageError -> 400

        db.session.commit()

        has_summary_now = bool(r.summary and r.summary.strip())

        snapshot_type = "machine_draft" if (not had_summary_before and has_summary_now) else "saved_revision"
        study_account = get_active_study_account(g.user_id)

        if study_account:
            study_session = get_or_create_active_study_session(study_account, g.user_id)

            snapshot = create_artifact_snapshot(
                study_session_id=study_session.id,
                flowchart_id=r.flowchart_id,
                snapshot_type=snapshot_type,
                image_data_url=flowchart_image_data_url(r),
                image_mime=r.image_mime,
                json_data=json.loads(r.json_data) if r.json_data else None,
                short_alt=r.short_alt,
                summary=r.summary,
                title=r.title,
                public_slug=r.public_slug,
            )
            touch_study_session(study_session)
            print("Created artifact snapshot:", snapshot.id)
        return jsonify(serialize_flowchart(r, include_json=True)), 200

    except ImageError as e:
        db.session.rollback()
        return error(400, str(e))
    except Exception as e:
        print("Error in PUT /flowcharts/<flowchart_id>:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))

@api_bp.route("/flowcharts/<flowchart_id>", methods=["DELETE"])
@require_auth
def delete_flowchart(flowchart_id):
    """
    Soft delete.
    """
    try:
        r = get_owned_flowchart_or_404(flowchart_id)
        if not r:
            return error(404, "Flowchart not found")
        r.deleted_at = datetime.utcnow()
        set_flowchart_image(r, None)  # deleting a STEM image deletes its original too
        db.session.commit()
        return jsonify({"flowchart_id": flowchart_id, "deleted": True}), 200
    except Exception as e:
        print("Error in DELETE /flowcharts/<flowchart_id>:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))


# -------- Sharing (who can see it) --------
@api_bp.route("/flowcharts/<flowchart_id>/sharing", methods=["PUT"])
@require_auth
def set_sharing(flowchart_id):
    """
    One setting for who can see a diagram. Replaces the separate publish + repo-visibility calls.
    Body: {"sharing": "public" | "link" | "private", "image_public": bool (optional)}
      public  -> has a /p/<slug> page and is listed in Browse
      link    -> has a /p/<slug> page, not listed
      private -> only the owner
    image_public controls whether the uploaded source image is shown on the shared page.
    """
    try:
        r = get_owned_flowchart_or_404(flowchart_id)
        if not r:
            return error(404, "Flowchart not found")

        data = request.get_json(silent=True) or {}
        sharing = data.get("sharing")
        if sharing not in SHARING_STATES:
            return error(400, "sharing must be 'public', 'link', or 'private'")
        if "image_public" in data and not isinstance(data["image_public"], bool):
            return error(400, "image_public must be true or false")

        apply_sharing(r, sharing)
        if "image_public" in data:
            r.image_public = data["image_public"]

        db.session.commit()
        return jsonify({
            **serialize_flowchart(r, include_json=False),
            "public_url": f"/p/{r.public_slug}" if r.is_published and r.public_slug else None,
        }), 200

    except Exception as e:
        print("Error in PUT /flowcharts/<flowchart_id>/sharing:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))


# -------- Publishing (permalink) --------
@api_bp.route("/publish/<flowchart_id>", methods=["POST"])
@require_auth
def publish_flowchart(flowchart_id):
    """
    Controls permalink publishing.
    Does NOT control repository discoverability.
    """
    try:
        r = get_owned_flowchart_or_404(flowchart_id)
        if not r:
            return error(404, "Flowchart not found")

        data = request.get_json(silent=True) or {}
        publish = bool(data.get("publish", True))

        # Deprecated: use PUT /flowcharts/<id>/sharing. Kept so older clients keep working.
        if publish:
            apply_sharing(r, "public" if r.visibility == "public" else "link")
        else:
            apply_sharing(r, "private")

        db.session.commit()

        return jsonify({
            "flowchart_id": r.flowchart_id,
            "is_published": r.is_published,
            "public_slug": r.public_slug,
            "public_url": f"/p/{r.public_slug}" if r.is_published and r.public_slug else None,
        }), 200

    except Exception as e:
        print("Error in POST /publish/<flowchart_id>:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))

@api_bp.route("/p/<public_slug>", methods=["GET"])
def get_published_flowchart(public_slug):
    r = (
        Flowchart.query
        .filter_by(public_slug=public_slug, is_published=True)
        .filter(Flowchart.deleted_at.is_(None))
        .first()
    )
    if not r:
        return error(404, "Not found")
    return jsonify(serialize_flowchart(r, include_json=True, public_mode=True)), 200



@api_bp.route("/p/<public_slug>/image", methods=["GET"])
def get_published_flowchart_image(public_slug):
    r = (
        Flowchart.query
        .filter_by(public_slug=public_slug, is_published=True, image_public=True)
        .filter(Flowchart.deleted_at.is_(None))
        .first()
    )
    url = flowchart_image_data_url(r) if r else None
    if not url:
        return error(404, "Not found")
    return jsonify({"image_data_url": url, "image_mime": r.image_mime}), 200

# -------- Repo visibility (discoverability) --------
@api_bp.route("/research/<flowchart_id>", methods=["POST"])
@require_auth
def set_repo_visibility(flowchart_id):
    """
    visibility controls discoverability in an open repository listing.
    Expected JSON: {"visibility": "public"|"private"}
    """
    try:
        r = get_owned_flowchart_or_404(flowchart_id)
        if not r:
            return error(404, "Flowchart not found")

        data = request.get_json(silent=True) or {}
        v = data.get("visibility")
        if v not in ["public", "private"]:
            return error(400, "visibility must be 'public' or 'private'")

        # Deprecated: use PUT /flowcharts/<id>/sharing. "public" now also publishes, so a row
        # can no longer be marked public yet stay invisible.
        apply_sharing(r, "public" if v == "public" else ("link" if r.is_published else "private"))
        db.session.commit()
        return jsonify({"flowchart_id": r.flowchart_id, "visibility": r.visibility, "sharing": current_sharing(r)}), 200

    except Exception as e:
        print("Error in POST /repo/<flowchart_id>:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))

@api_bp.route("/repo", methods=["GET"])
def list_repo_flowcharts():
    """
    Public listing endpoint for the open repo.
    (Recommended: only show items that are BOTH repo-public AND permalink-published.)
    """
    rows = (
        Flowchart.query
        .filter_by(visibility="public", is_published=True)
        .filter(Flowchart.deleted_at.is_(None))
        .order_by(Flowchart.published_at.desc().nullslast())
        .all()
    )
    return jsonify([serialize_flowchart(r, include_json=False, public_mode=True) for r in rows]), 200

# ----- Pilot Specific Help ----- #
@api_bp.route("/flowcharts/<flowchart_id>/finalize-export", methods=["POST"])
@require_auth
def finalize_export_snapshot(flowchart_id):
    """
    Create a final_verified artifact snapshot when a study participant exports.
    Accepts optional JSON metadata such as export_type.
    """
    try:
        r = get_owned_flowchart_or_404(flowchart_id)
        if not r:
            return error(404, "Flowchart not found")

        data = request.get_json(silent=True) or {}
        export_type = data.get("export_type")

        study_account = get_active_study_account(g.user_id)

        if not study_account:
            return jsonify({
                "ok": True,
                "logged": False,
                "reason": "user is not an active study account"
            }), 200

        study_session = get_or_create_active_study_session(study_account, g.user_id)

        snapshot = create_artifact_snapshot(
            study_session_id=study_session.id,
            flowchart_id=r.flowchart_id,
            snapshot_type="final_verified",
            file_name=None,
            image_data_url=flowchart_image_data_url(r),
            image_mime=r.image_mime,
            json_data=json.loads(r.json_data) if r.json_data else None,
            short_alt=r.short_alt,
            summary=r.summary,
            title=r.title,
            public_slug=r.public_slug,
            metadata_json={
                "export_type": export_type
            } if export_type else None,
        )
        touch_study_session(study_session)

        print("Created final_verified snapshot:", snapshot.id)

        return jsonify({
            "ok": True,
            "logged": True,
            "snapshot_id": snapshot.id,
            "snapshot_type": snapshot.snapshot_type,
            "study_session_id": study_session.id,
            "flowchart_id": r.flowchart_id,
            "export_type": export_type,
        }), 200

    except Exception as e:
        print("Error in POST /flowcharts/<flowchart_id>/finalize-export:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))
    """
    Create a final_verified artifact snapshot when a study participant exports.
    This should be a best-effort study logging endpoint and should not modify
    the underlying flowchart itself.
    """


@api_bp.route("/research-events", methods=["POST"])
@require_auth
def log_research_event_route():
    try:
        data = request.get_json(silent=True) or {}

        event_type = data.get("event_type")
        if not event_type:
            return error(400, "Missing required field: event_type")

        event_category = EVENT_TYPES.get(event_type)
        if not event_category:
            return error(400, f"Unknown event_type: {event_type}")

        study_account = get_active_study_account(g.user_id)
        if not study_account:
            return jsonify({"ok": True, "logged": False, "reason": "no_active_study_account"}), 200

        study_session = get_or_create_active_study_session(study_account, g.user_id)

        event = create_research_event(
            study_session_id=study_session.id,
            flowchart_id=data.get("flowchart_id"),
            artifact_snapshot_id=data.get("artifact_snapshot_id"),
            event_type=event_type,
            event_category=event_category,
            editor_mode=data.get("editor_mode"),
            representation_type=data.get("representation_type"),
            success=data.get("success"),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            event_data=data.get("event_data"),
        )

        touch_study_session(study_session)

        return jsonify({"ok": True, "logged": True, "research_event_id": event.id}), 201

    except Exception as e:
        print("Error in POST /research-events:", traceback.format_exc())
        db.session.rollback()
        return error(500, str(e))
# -------------------------
# Mermaid export helper (kept because /upload uses it)
# -------------------------
def json_to_mermaid(json_data):
    graph_direction = json_data.get('graph', 'TD')
    nodes = json_data['nodes']
    edges = json_data['edges']

    shape_mapping = {
        "circle": "(($label$))",
        "rectangle": "[$label$]",
        "stadium": "([$label$])",
        "diamond": "{$label$}",
        "hexagon": "{{$label$}}",
        "parallelogram": "[/$label$/]",
        "cylinder": "[($label$)]",
        "unknown": "[$label$]"
    }

    def format_label(label):
        return f'"{str(label or "").replace("\n", "<br>")}"'

    mermaid_nodes = [
        f"{node['id']}{shape_mapping.get(node['shape'], '[$label$]').replace('$label$', format_label(node['label']))}"
        for node in nodes
    ]
    mermaid_edges = [
        f"{edge['source']} -->|{format_label(edge['label'])}| {edge['destination']}" if edge['label'] else f"{edge['source']} -->| | {edge['destination']}"
        for edge in edges
    ]
    return f"flowchart {graph_direction}\n" + "\n".join(mermaid_nodes + mermaid_edges)

def generate_flowchart_description(flowchart_data):
    descriptions = "Nodes:\n"
    
    # Map of node ids to labels for easier edge referencing
    node_map = {node['id']: node['label'] for node in flowchart_data['nodes']}
    
    # Create node descriptions
    for i, node in enumerate(flowchart_data['nodes'], start=1):
        descriptions += f'Node {i}: "{node["label"]}" ({node["shape"]})\n'
    
    descriptions += "\nEdges:\n"
    
    # Create edge descriptions
    for edge in flowchart_data['edges']:
        source_label = node_map[edge['source']]
        destination_label = node_map[edge['destination']]
        edge_label = edge.get('label', '')
        if edge_label:
            descriptions += f'From "{source_label}" ({edge_label}) to "{destination_label}"\n'
        else:
            descriptions += f'From "{source_label}" to "{destination_label}"\n'
    
    return descriptions

from typing import Any, Dict, Union

# Function to encode the image
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")   
# new upload svg route 



# Long descriptions are made on the public /ld page, which has no sign-in, so they are stored with a
# fixed placeholder owner. (owner_id is NOT NULL; the old code never set it, so every save was a 500.)
ANONYMOUS_OWNER = "anonymous"
LONGDESC_SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
LONGDESC_MAX_ALT = 2_000
LONGDESC_MAX_MARKDOWN = 50_000
LONGDESC_MAX_TITLE = 255
LONGDESC_MAX_IMAGE = 5_000_000   # characters of the data: URL, about 3.7 MB of image
LONGDESC_PER_IP_PER_HOUR = 30          # text-only saves, anyone
LONGDESC_IMAGES_PER_USER_PER_HOUR = 20
LONGDESC_MAX_IMAGES_PER_USER = 100     # stored images an account may keep


@api_bp.route('/longdesc', methods=['POST'])
def create_long_description():
    """
    Create a permalink entry for a complex image. Text-only entries are open to anyone (the /ld
    page works without an account), so their size and rate are limited. An entry that includes an
    image is the expensive kind to store, so it needs a signed-in account (Authorization: Bearer
    ...), which also gives it a real owner and a per-account limit.
    Expects JSON:
      {
        "alt_text": "...",
        "long_markdown": "...",
        "title": "..." (optional),
        "image_data_url": "data:image/png;base64,...." (optional),
        "slug": "optional-custom-id"  (3-64 letters, digits, - or _)
      }
    Returns: { "id": "<slug>", ... }
    """
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({'error': 'Expected a JSON object'}), 400

        alt_text = data.get('alt_text')
        long_markdown = data.get('long_markdown')
        image_data_url = data.get('image_data_url')
        title = data.get('title')
        slug = data.get('slug') or uuid.uuid4().hex[:12]  # short permalink id
        image_public = data.get('image_public', False)  # private unless the author chooses
        if not isinstance(image_public, bool):
            return jsonify({'error': 'image_public must be true or false'}), 400

        if not alt_text or not long_markdown:
            return jsonify({'error': 'alt_text and long_markdown are required'}), 400

        for name, value, limit in (
            ('alt_text', alt_text, LONGDESC_MAX_ALT),
            ('long_markdown', long_markdown, LONGDESC_MAX_MARKDOWN),
        ):
            if not isinstance(value, str):
                return jsonify({'error': f'{name} must be text'}), 400
            if len(value) > limit:
                return jsonify({'error': f'{name} can be at most {limit} characters'}), 400
        if title is not None and (not isinstance(title, str) or len(title) > LONGDESC_MAX_TITLE):
            return jsonify({'error': f'title must be text of at most {LONGDESC_MAX_TITLE} characters'}), 400
        if image_data_url is not None:
            if not isinstance(image_data_url, str) or not image_data_url.startswith('data:image/'):
                return jsonify({'error': 'image_data_url must be an image data: URL'}), 400
            if len(image_data_url) > LONGDESC_MAX_IMAGE:
                return jsonify({'error': 'The image is too large'}), 400
        if not isinstance(slug, str) or not LONGDESC_SLUG_RE.match(slug):
            return jsonify({'error': 'slug must be 3-64 letters, digits, - or _'}), 400

        owner_id = ANONYMOUS_OWNER
        if image_data_url:
            user_id = optional_user()
            if not user_id:
                return jsonify({'error': 'Sign in to save a long description with an image.'}), 401
            owner_id = user_id
            if not limiter.allow("ld-img:" + user_id, LONGDESC_IMAGES_PER_USER_PER_HOUR):
                return jsonify({'error': 'Too many saves. Please wait a while and try again.'}), 429
            kept = (
                LongDescription.query.filter_by(owner_id=user_id)
                .filter(db.or_(LongDescription.image_id.isnot(None), LongDescription.image_data_url.isnot(None)))
                .count()
            )
            if kept >= LONGDESC_MAX_IMAGES_PER_USER:
                return jsonify({'error': f'You can keep up to {LONGDESC_MAX_IMAGES_PER_USER} long descriptions with images.'}), 409
        elif not limiter.allow("ld:" + client_ip(), LONGDESC_PER_IP_PER_HOUR):
            return jsonify({'error': 'Too many saves. Please wait a while and try again.'}), 429

        # Ensure slug is unique
        existing = LongDescription.query.filter_by(slug=slug).first()
        if existing:
            return jsonify({'error': 'Slug already exists, choose a different one'}), 400

        record = LongDescription(
            slug=slug,
            owner_id=owner_id,
            alt_text=alt_text,
            long_markdown=long_markdown,
            title=title,
            image_public=image_public,
        )
        # The image goes to the shared image store, not onto this row. ImageError -> 400 below.
        set_flowchart_image(record, image_data_url)

        db.session.add(record)
        db.session.commit()

        return jsonify({
            'id': record.slug,
            'alt_text': record.alt_text,
            'long_markdown': record.long_markdown,
            'image_data_url': flowchart_image_data_url(record),
            'image_public': bool(record.image_public),
            'title': record.title,
        }), 201

    except ImageError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception:
        # Log the detail; do not hand SQL or stack traces back to an anonymous caller.
        print("Error in /longdesc (POST):", traceback.format_exc())
        db.session.rollback()
        return jsonify({'error': 'Internal Server Error'}), 500

@api_bp.route('/longdesc/<slug>', methods=['GET'])
def get_long_description(slug):
    """
    Retrieve a previously saved long description by its permalink slug.
    Returns JSON:
      {
        "id": "<slug>",
        "alt_text": "...",
        "long_markdown": "..."
         "image_data_url": "data:image/png;base64,..."
      }
    """
    try:
        record = LongDescription.query.filter_by(slug=slug).first()
        if not record:
            return jsonify({'error': 'Long description not found'}), 404

        # Visitors see the image only when the author chose to show it; the author always can.
        has_image = bool(record.image_id or record.image_data_url)
        viewer = optional_user()
        is_owner = bool(viewer) and viewer == record.owner_id
        show_image = has_image and (bool(record.image_public) or is_owner)

        return jsonify({
            'id': record.slug,
            'alt_text': record.alt_text,
            'long_markdown': record.long_markdown,
            'image_data_url': flowchart_image_data_url(record) if show_image else None,
            'has_image': has_image,
            'image_public': bool(record.image_public),
            'title': record.title,
        }), 200

    except Exception:
        print("Error in /longdesc/<slug> (GET):", traceback.format_exc())
        return jsonify({'error': 'Internal Server Error'}), 500


@api_bp.route('/longdesc/<slug>/sharing', methods=['PUT'])
@require_auth
def set_long_description_image_sharing(slug):
    """Owner-only. Body: {"image_public": true|false} - whether visitors to the shared page see
    the image."""
    try:
        record = LongDescription.query.filter_by(slug=slug, owner_id=g.user_id).first()
        if not record:
            return jsonify({'error': 'Long description not found'}), 404
        value = (request.get_json(silent=True) or {}).get('image_public')
        if not isinstance(value, bool):
            return jsonify({'error': 'image_public must be true or false'}), 400
        record.image_public = value
        db.session.commit()
        return jsonify({'id': slug, 'image_public': record.image_public}), 200
    except Exception:
        print("Error in /longdesc/<slug>/sharing (PUT):", traceback.format_exc())
        db.session.rollback()
        return jsonify({'error': 'Internal Server Error'}), 500


@api_bp.route('/longdesc/<slug>', methods=['DELETE'])
@require_auth
def delete_long_description(slug):
    """Delete a long description and its image. Only the signed-in owner can; entries saved
    without an account (owner "anonymous") have no owner and cannot be deleted here."""
    try:
        record = LongDescription.query.filter_by(slug=slug, owner_id=g.user_id).first()
        if not record:
            return jsonify({'error': 'Long description not found'}), 404
        set_flowchart_image(record, None)  # removes the stored bytes
        db.session.delete(record)
        db.session.commit()
        return jsonify({'id': slug, 'deleted': True}), 200
    except Exception:
        print("Error in /longdesc/<slug> (DELETE):", traceback.format_exc())
        db.session.rollback()
        return jsonify({'error': 'Internal Server Error'}), 500

