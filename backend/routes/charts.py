"""Chart permalinks: save a chart from the Charts page and open it again from a link.

    POST   /charts                    create (sign-in required); shared by link unless "private"
    GET    /charts                    your charts, newest first (no data)
    GET    /charts/<chart_id>         one of your charts, with its data
    PUT    /charts/<chart_id>         change title, data, settings or spec
    PUT    /charts/<chart_id>/sharing "public", "link" or "private"
    DELETE /charts/<chart_id>         remove it (its link stops working)
    GET    /c/<public_slug>           public: the chart behind a shared link

Charts use the same sharing model as STEM images ("public", "link", "private"). "public" is
stored and reported, but there is no chart listing yet (/repo lists STEM images only), so until
one exists a public chart is reachable only through its link, exactly like "link".
"""
import json
import traceback
import uuid
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from backend.auth import require_auth
from backend.chart_validation import (
    MAX_TITLE,
    ChartValidationError,
    clean_config,
    clean_dataset,
    clean_spec,
    _text,
)
from backend.db import db
from backend.models import Chart
from backend.routes.api import SHARING_STATES, apply_sharing, current_sharing

charts_bp = Blueprint("charts", __name__)

MAX_CHARTS_PER_USER = 200


def _error(status, msg):
    return jsonify({"error": msg}), status


def serialize_chart(r, include_data=True, public=False):
    sharing = current_sharing(r)
    out = {
        "title": r.title,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }
    if public:
        out["public_slug"] = r.public_slug
    else:
        out.update(
            chart_id=r.chart_id,
            sharing=sharing,
            is_published=bool(r.is_published),
            public_slug=r.public_slug if r.is_published else None,
            public_url=f"/charts/{r.public_slug}" if (r.is_published and r.public_slug) else None,
        )
    if include_data:
        out["dataset"] = json.loads(r.dataset_json)
        out["config"] = json.loads(r.config_json)
        out["spec"] = json.loads(r.spec_json) if r.spec_json else None
    return out


def _owned(chart_id):
    return Chart.query.filter_by(chart_id=chart_id, owner_id=g.user_id).filter(Chart.deleted_at.is_(None)).first()


def _title_from(data, config, dataset):
    explicit = _text(data.get("title"), "title", MAX_TITLE)
    return explicit or config.get("title") or dataset.get("name")


@charts_bp.route("/charts", methods=["POST"])
@require_auth
def create_chart():
    try:
        data = request.get_json(silent=True) or {}
        sharing = data.get("sharing", "link")
        if sharing not in SHARING_STATES:
            return _error(400, "sharing must be 'public', 'link', or 'private'")

        dataset = clean_dataset(data.get("dataset"))
        config = clean_config(data.get("config"), dataset["columns"])
        spec = clean_spec(data.get("spec"))

        owned = Chart.query.filter_by(owner_id=g.user_id).filter(Chart.deleted_at.is_(None)).count()
        if owned >= MAX_CHARTS_PER_USER:
            return _error(409, f"You can keep up to {MAX_CHARTS_PER_USER} charts; delete one to save another")

        r = Chart(
            chart_id=str(uuid.uuid4()),
            owner_id=g.user_id,
            title=_title_from(data, config, dataset),
            dataset_json=json.dumps(dataset, ensure_ascii=False),
            config_json=json.dumps(config, ensure_ascii=False),
            spec_json=json.dumps(spec, ensure_ascii=False) if spec else None,
        )
        apply_sharing(r, sharing)
        db.session.add(r)
        db.session.commit()
        return jsonify(serialize_chart(r)), 201
    except ChartValidationError as e:
        db.session.rollback()
        return _error(400, str(e))
    except Exception:
        print("Error in POST /charts:", traceback.format_exc())
        db.session.rollback()
        return _error(500, "Internal Server Error")


@charts_bp.route("/charts", methods=["GET"])
@require_auth
def list_charts():
    rows = (
        Chart.query.filter_by(owner_id=g.user_id)
        .filter(Chart.deleted_at.is_(None))
        .order_by(Chart.created_at.desc())
        .all()
    )
    return jsonify([serialize_chart(r, include_data=False) for r in rows]), 200


@charts_bp.route("/charts/<chart_id>", methods=["GET"])
@require_auth
def get_chart(chart_id):
    r = _owned(chart_id)
    return (jsonify(serialize_chart(r)), 200) if r else _error(404, "Chart not found")


@charts_bp.route("/charts/<chart_id>", methods=["PUT"])
@require_auth
def update_chart(chart_id):
    try:
        r = _owned(chart_id)
        if not r:
            return _error(404, "Chart not found")
        data = request.get_json(silent=True) or {}

        dataset = json.loads(r.dataset_json)
        if "dataset" in data:
            dataset = clean_dataset(data["dataset"])
            r.dataset_json = json.dumps(dataset, ensure_ascii=False)
        # Settings are re-checked against the (possibly new) columns either way.
        config_in = data["config"] if "config" in data else json.loads(r.config_json)
        config = clean_config(config_in, dataset["columns"])
        r.config_json = json.dumps(config, ensure_ascii=False)
        if "spec" in data:  # null removes it
            spec = clean_spec(data["spec"])
            r.spec_json = json.dumps(spec, ensure_ascii=False) if spec else None
        if "title" in data:
            r.title = _text(data.get("title"), "title", MAX_TITLE)
        db.session.commit()
        return jsonify(serialize_chart(r)), 200
    except ChartValidationError as e:
        db.session.rollback()
        return _error(400, str(e))
    except Exception:
        print("Error in PUT /charts:", traceback.format_exc())
        db.session.rollback()
        return _error(500, "Internal Server Error")


@charts_bp.route("/charts/<chart_id>/sharing", methods=["PUT"])
@require_auth
def set_chart_sharing(chart_id):
    r = _owned(chart_id)
    if not r:
        return _error(404, "Chart not found")
    sharing = (request.get_json(silent=True) or {}).get("sharing")
    if sharing not in SHARING_STATES:
        return _error(400, "sharing must be 'public', 'link', or 'private'")
    apply_sharing(r, sharing)
    db.session.commit()
    return jsonify(serialize_chart(r, include_data=False)), 200


@charts_bp.route("/charts/<chart_id>", methods=["DELETE"])
@require_auth
def delete_chart(chart_id):
    r = _owned(chart_id)
    if not r:
        return _error(404, "Chart not found")
    # Soft delete, and unpublish so an old link cannot keep serving a chart its owner removed.
    r.deleted_at = datetime.utcnow()
    r.is_published = False
    r.published_at = None
    db.session.commit()
    return jsonify({"ok": True}), 200


@charts_bp.route("/c/<public_slug>", methods=["GET"])
def get_public_chart(public_slug):
    r = (
        Chart.query.filter_by(public_slug=public_slug, is_published=True)
        .filter(Chart.deleted_at.is_(None))
        .first()
    )
    if not r:
        return _error(404, "Chart not found")
    return jsonify(serialize_chart(r, public=True)), 200
