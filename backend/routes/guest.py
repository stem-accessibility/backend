import json
import traceback
import uuid

from flask import Blueprint, g, jsonify, request

from backend.auth import require_auth
from backend.db import db
from backend.guest import (
    LIMIT_REPORTS_PER_IP,
    client_ip,
    guest_owner_id,
    is_guest_owner,
    limiter,
    require_guest,
    validate_payload,
    _TOKEN_RE,
)
from backend.models import Flowchart, Report
from backend.routes.api import apply_sharing, serialize_flowchart

guest_bp = Blueprint("guest", __name__)


def _error(status, msg):
    return jsonify({"error": msg}), status


def _current(owner):
    return (
        Flowchart.query.filter_by(owner_id=owner)
        .filter(Flowchart.deleted_at.is_(None))
        .order_by(Flowchart.created_at.desc())
        .first()
    )


@guest_bp.route("/guest/image", methods=["GET"])
@require_guest
def get_guest_image():
    r = _current(g.guest_owner)
    if not r:
        return jsonify(None), 200
    return jsonify(serialize_flowchart(r, include_json=True)), 200


@guest_bp.route("/guest/image", methods=["PUT"])
@require_guest
def put_guest_image():
    """Create the guest's one STEM image, or update it. Always shared publicly; no source image."""
    try:
        clean, err = validate_payload(request.get_json(silent=True) or {})
        if err:
            return _error(400, err)

        r = _current(g.guest_owner)
        created = r is None
        if created:
            r = Flowchart(
                flowchart_id=str(uuid.uuid4()),
                owner_id=g.guest_owner,
                json_data=json.dumps(clean["json_data"]),
            )
            db.session.add(r)

        r.json_data = json.dumps(clean["json_data"])
        r.title = clean["title"]
        r.short_alt = clean["short_alt"]
        r.summary = clean["summary"]
        r.flowchart_type = clean["flowchart_type"]
        r.image_data_url = None
        r.image_mime = None
        r.image_public = False
        apply_sharing(r, "public")

        db.session.commit()
        return jsonify(serialize_flowchart(r, include_json=True)), (201 if created else 200)
    except Exception as e:
        print("Error in PUT /guest/image:", traceback.format_exc())
        db.session.rollback()
        return _error(500, str(e))


@guest_bp.route("/guest/image", methods=["DELETE"])
@require_guest
def delete_guest_image():
    r = _current(g.guest_owner)
    if not r:
        return jsonify({"deleted": False}), 200
    from datetime import datetime

    apply_sharing(r, "private")
    r.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"deleted": True}), 200


@guest_bp.route("/guest/claim", methods=["POST"])
@require_auth
def claim_guest_image():
    """After signing up or in, move the guest's image into the account (the token proves it is theirs)."""
    token = request.headers.get("X-Guest-Token", "").strip()
    if not _TOKEN_RE.match(token):
        return _error(400, "Missing or invalid X-Guest-Token")
    r = _current(guest_owner_id(token))
    if not r:
        return jsonify({"claimed": False}), 200
    r.owner_id = g.user_id
    db.session.commit()
    return jsonify({"claimed": True, "flowchart_id": r.flowchart_id}), 200


@guest_bp.route("/p/<public_slug>/report", methods=["POST"])
def report_public_page(public_slug):
    """Anyone can report a public page. Reports are stored for review; nothing is removed automatically."""
    if not limiter.allow("report:" + client_ip(), LIMIT_REPORTS_PER_IP):
        return _error(429, "Too many reports. Please wait a while and try again.")
    r = (
        Flowchart.query.filter_by(public_slug=public_slug, is_published=True)
        .filter(Flowchart.deleted_at.is_(None))
        .first()
    )
    if not r:
        return _error(404, "Not found")
    reason = ((request.get_json(silent=True) or {}).get("reason") or "").strip()[:500]
    db.session.add(Report(public_slug=public_slug, reason=reason or None))
    db.session.commit()
    return jsonify({"reported": True}), 201


GUEST_EXTRACTIONS_PER_IP_PER_HOUR = 20
GUEST_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


@guest_bp.route("/guest/extract-chart", methods=["POST"])
@require_guest
def guest_extract_chart():
    """Read a chart image into a table, for visitors without an account.

    Guests may use only the built-in reader: the image is never sent to a third party or to an AI
    model, so this route never passes allow_llm and never selects the LLM extractor. It runs in the
    request (guests have no job queue), keeps nothing, and is rate-limited per address.
    """
    import os
    import tempfile

    from backend.chart_validation import ChartValidationError
    from backend.pipeline.chart_extract import ExtractionError, extract_chart, extraction_options
    from backend.pipeline.chart_result import build_chart_result

    if not extraction_options()["local"]:
        return _error(503, "Reading chart images is not available right now. Upload a CSV instead.")
    if not limiter.allow("gx:" + client_ip(), GUEST_EXTRACTIONS_PER_IP_PER_HOUR):
        return _error(429, "Too many charts read. Please wait a while and try again.")

    file = request.files.get("file")
    if not file or not file.filename:
        return _error(400, "No file provided")
    if file.mimetype not in GUEST_IMAGE_TYPES:
        return _error(400, "Upload a PNG, JPEG or WebP image")
    try:
        limit = int(os.environ.get("MAX_CHART_IMAGE_BYTES", str(8 * 1024 * 1024)))
    except ValueError:
        limit = 8 * 1024 * 1024
    data = file.read(limit + 1)
    if not data:
        return _error(400, "Empty file")
    if len(data) > limit:
        return _error(413, f"Image is larger than {max(limit // (1024 * 1024), 1)} MB")

    suffix = {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(file.mimetype, ".png")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        x = extract_chart(path, allow_llm=False, mode="unichart")
        return jsonify(build_chart_result(x)), 200
    except ExtractionError as e:
        return _error(502, str(e))
    except ChartValidationError as e:
        return _error(422, f"The chart could not be read as a table: {e}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
