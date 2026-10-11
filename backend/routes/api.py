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
import numpy as np
from io import BytesIO
from backend.db import db
#from backend.pipeline.pipeline import process_image
from backend.pipeline.pipeline2 import process_image
from dotenv import load_dotenv
from backend.mermaid_parser import parse_mermaid_flowchart_td
from backend.auth import require_auth
from flask import g
import tempfile
from backend.descriptions.deterministic_longdesc import build_deterministic_outline
from backend.descriptions.summary_service import generate_summary_bundle
import uuid
# Import models after initializing db to avoid circular imports
from backend.models import Flowchart, LongDescription
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

def serialize_flowchart(r: Flowchart, include_json: bool = True, public_mode: bool = False):
    has_image = bool(getattr(r, "image_data_url", None))

    if public_mode:
        image_endpoint = f"/p/{r.public_slug}/image" if (has_image and r.public_slug and r.is_published) else None
    else:
        image_endpoint = f"/get/{r.flowchart_id}/image" if has_image else None

    payload = {
        "flowchart_id": r.flowchart_id,
        "title": getattr(r, "title", None),
        "short_alt": getattr(r, "short_alt", None),
        "visibility": getattr(r, "visibility", "private"),
        "flowchart_type": getattr(r, "flowchart_type", "unknown"),
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
    Optional: flowchart_id, title, short_alt, visibility, flowchart_type, image_data_url, image_mime
    """
    try:
        data = request.get_json(silent=True) or {}

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
            visibility=data.get("visibility", "private"),
            flowchart_type=data.get("flowchart_type", "unknown"),
            image_data_url=data.get("image_data_url"),
            image_mime=data.get("image_mime"),
        )

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
                image_data_url=r.image_data_url,
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
    if not r or not r.image_data_url:
        return error(404, "Image not found")
    return jsonify({"image_data_url": r.image_data_url, "image_mime": r.image_mime}), 200


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
            r.image_data_url = data["image_data_url"]
        if "image_mime" in data:
            r.image_mime = data["image_mime"]

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
                image_data_url=r.image_data_url,
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
        db.session.commit()
        return jsonify({"flowchart_id": flowchart_id, "deleted": True}), 200
    except Exception as e:
        print("Error in DELETE /flowcharts/<flowchart_id>:", traceback.format_exc())
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

        if publish:
            if not r.public_slug:
                r.public_slug = uuid.uuid4().hex[:12]
            r.is_published = True
            r.published_at = datetime.utcnow()
        else:
            r.is_published = False
            r.published_at = None

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
    return jsonify(serialize_flowchart(r, include_json=True)), 200



@api_bp.route("/p/<public_slug>/image", methods=["GET"])
def get_published_flowchart_image(public_slug):
    r = (
        Flowchart.query
        .filter_by(public_slug=public_slug, is_published=True)
        .filter(Flowchart.deleted_at.is_(None))
        .first()
    )
    if not r or not r.image_data_url:
        return error(404, "Not found")
    return jsonify({"image_data_url": r.image_data_url, "image_mime": r.image_mime}), 200

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

        r.visibility = v
        db.session.commit()
        return jsonify({"flowchart_id": r.flowchart_id, "visibility": r.visibility}), 200

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

# -------- Image processing pipeline --------
@api_bp.route('/upload', methods=['POST'])
def upload():
    """
    Upload an image, run pipeline, return:
      - mermaid_json
      - mermaid_code
      - image_data_url (base64)
      - image_mime
    """
    try:
        if "file" not in request.files:
            return error(400, "No file provided")

        file = request.files["file"]
        img_bytes = file.read()
        if not img_bytes:
            return error(400, "Empty file")

        # Write to temp file for your existing pipeline
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(img_bytes)
            tmp_path = tmp.name

        try:
            json_data = process_image(tmp_path, base_name="uploaded")
            mermaid_code = json_to_mermaid(json_data)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

        image_data_url = "data:image/png;base64," + base64.b64encode(img_bytes).decode("utf-8")

        return jsonify({
            "mermaid_json": json_data,
            "mermaid_code": mermaid_code,
            "image_data_url": image_data_url,
            "image_mime": "image/png",
            "message": "Successfully processed image.",
        }), 200

    except Exception as e:
        print("Error in /upload:", traceback.format_exc())
        return error(500, str(e))

@api_bp.route("/generate-outline", methods=["POST"])
def generate_outline():
  """
  Deterministic (no LLM):
  Input: diagram JSON (either raw, or { "diagram": {...} })
  Output: { diagram_type, outline_markdown }
  """
  try:
    payload = request.get_json(silent=True) or {}
    diagram_json = payload.get("diagram", payload)

    if not diagram_json:
      return jsonify({"error": "No JSON payload provided."}), 400

    result = build_deterministic_outline(diagram_json)
    return jsonify(result), 200

  except Exception as e:
    print("Error in /generate-outline:", traceback.format_exc())
    return jsonify({"error": str(e)}), 500
  
@api_bp.route('/generate-summary', methods=['POST'])
def generate_summary():
  try:
    payload = request.get_json(silent=True) or {}
    if not payload:
      return jsonify({"error": "No JSON payload provided."}), 400

    # frontend may send { diagram: {...}, mode: "hybrid" }
    diagram_json = payload.get("diagram", payload)
    mode = payload.get("mode", "hybrid")  # "deterministic" | "hybrid"
    model = None  # client-supplied model names are ignored; use llm.MODEL_SUMMARY

    bundle = generate_summary_bundle(
      diagram_json=diagram_json,
      mode=mode,
      model=model,
    )

    return jsonify({
      "short_alt": bundle["short_alt"],
      "summary": bundle["long_markdown"],
      "diagram_type": bundle["diagram_type"],
      "outline_markdown": bundle["outline_markdown"],
    }), 200

  except Exception as e:
    print("Error in /generate-summary:", traceback.format_exc())
    return jsonify({"error": str(e)}), 500

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
            image_data_url=r.image_data_url,
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



@api_bp.route('/longdesc', methods=['POST'])
def create_long_description():
    """
    Create a permalink entry for a complex image.
    Expects JSON:
      {
        "alt_text": "...",
        "long_markdown": "...",
        "image_data_url": "data:image/png;base64,...." (optional),
        "slug": "optional-custom-id"
      }
    Returns: { "id": "<slug>" }
    """
    try:
        data = request.json or {}
        alt_text = data.get('alt_text')
        long_markdown = data.get('long_markdown')
        image_data_url = data.get('image_data_url')  # 🔹 NEW
        title = data.get('title')
        slug = data.get('slug') or uuid.uuid4().hex[:12]  # short permalink id

        if not alt_text or not long_markdown:
            return jsonify({'error': 'alt_text and long_markdown are required'}), 400

        # Ensure slug is unique
        existing = LongDescription.query.filter_by(slug=slug).first()
        if existing:
            return jsonify({'error': 'Slug already exists, choose a different one'}), 400

        record = LongDescription(
            slug=slug,
            alt_text=alt_text,
            long_markdown=long_markdown,
            image_data_url=image_data_url,
            title=title,
        )

        db.session.add(record)
        db.session.commit()

        return jsonify({
            'id': record.slug,
            'alt_text': record.alt_text,
            'long_markdown': record.long_markdown,
            'image_data_url': record.image_data_url,
            'title': record.title,
        }), 201

    except Exception as e:
        print("Error in /longdesc (POST):", traceback.format_exc())
        db.session.rollback()
        return jsonify({'error': f'Internal Server Error: {str(e)}'}), 500

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

        return jsonify({
            'id': record.slug,
            'alt_text': record.alt_text,
            'long_markdown': record.long_markdown,
            'image_data_url': record.image_data_url,
            'title': record.title,
        }), 200

    except Exception as e:
        print("Error in /longdesc/<slug> (GET):", traceback.format_exc())
        return jsonify({'error': f'Internal Server Error: {str(e)}'}), 500

