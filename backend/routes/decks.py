"""Owner-only PDF uploads/results; finished diagrams reuse the existing public routes."""

import datetime
import json
import os
import uuid

from flask import Blueprint, Request, g, jsonify, request

from backend.auth import require_auth
from backend.db import db
from backend.image_store import get_store, to_data_url
from backend.models import DeckDiagram, Flowchart, Job, SlideDeck
from backend.pipeline.deck_detection import DeckError, MAX_PDF_BYTES, inspect_pdf

decks_bp = Blueprint("decks", __name__)


class DeckUploadRequest(Request):
    """Per-route body limits, including Flask 3.0 where this property has no setter."""

    @property
    def max_content_length(self):
        if self.path == "/decks" and self.method == "POST":
            return MAX_PDF_BYTES + 1024 * 1024
        if self.path.startswith("/decks/") and self.path.endswith("/finalize"):
            return 1024 * 1024
        return super().max_content_length


def owned_deck(deck_id):
    return SlideDeck.query.filter_by(id=deck_id, owner_id=g.user_id).first_or_404()


def owned_item(deck_id, item_id):
    deck = owned_deck(deck_id)
    item = DeckDiagram.query.filter_by(id=item_id, deck_id=deck.id).first_or_404()
    return deck, item


@decks_bp.post("/decks")
@require_auth
def upload_deck():
    upload = request.files.get("file")
    if not upload:
        return jsonify(error="Choose a PDF slide deck."), 400
    if not os.environ.get("GEMINI_API_KEY"):
        return jsonify(error="The server needs GEMINI_API_KEY for slide deck uploads."), 503
    data = upload.read(MAX_PDF_BYTES + 1)
    try:
        count = inspect_pdf(data)
    except DeckError as exc:
        return jsonify(error=str(exc)), 400
    deck = SlideDeck(
        id=str(uuid.uuid4()),
        owner_id=g.user_id,
        filename=os.path.basename(upload.filename or "slides.pdf")[:255],
        pdf_data=data,
        page_count=count,
        pages_json=json.dumps([{"status": "pending"} for _ in range(count)]),
    )
    job = Job(type="process_deck", payload=json.dumps({"deck_id": deck.id}), owner_id=g.user_id)
    db.session.add_all([deck, job])
    db.session.flush()
    deck.job_id = job.id
    db.session.commit()
    # Always queue: rendering an entire deck must not block an HTTP request.
    return jsonify(id=deck.id), 202


@decks_bp.get("/decks")
@require_auth
def list_decks():
    decks = (
        SlideDeck.query.filter_by(owner_id=g.user_id)
        .order_by(SlideDeck.created_at.desc())
        .limit(30)
    )
    return jsonify(
        [{"id": d.id, "filename": d.filename, "page_count": d.page_count} for d in decks]
    )


@decks_bp.get("/decks/<deck_id>")
@require_auth
def get_deck(deck_id):
    deck = owned_deck(deck_id)
    job = db.session.get(Job, deck.job_id)
    items = (
        DeckDiagram.query.filter_by(deck_id=deck.id)
        .order_by(DeckDiagram.page_number, DeckDiagram.position)
        .all()
    )
    results = []
    for item in items:
        record = (
            Flowchart.query.filter_by(
                flowchart_id=item.flowchart_id, owner_id=g.user_id, deleted_at=None
            ).first()
            if item.flowchart_id
            else None
        )
        results.append(
            {
                "id": item.id,
                "page_number": item.page_number,
                "position": item.position,
                "title": item.title,
                "kind": item.kind,
                "status": item.status,
                "error": item.error,
                "flowchart_id": record.flowchart_id if record else None,
                "public_path": (
                    f"/p/{record.public_slug}" if record and record.is_published else None
                ),
                "graph": (
                    json.loads(record.json_data)
                    if record and item.status == "awaiting_description"
                    else None
                ),
            }
        )
    return jsonify(
        id=deck.id,
        filename=deck.filename,
        page_count=deck.page_count,
        pages=json.loads(deck.pages_json),
        items=results,
        job_status=job.status if job else "failed",
        error="Processing stopped. Retry the deck." if not job or job.status == "failed" else None,
    )


@decks_bp.get("/decks/<deck_id>/diagrams/<item_id>/image")
@require_auth
def get_crop(deck_id, item_id):
    deck, item = owned_item(deck_id, item_id)
    stored = get_store().get(item.image_id, deck.owner_id)
    if not stored:
        return jsonify(error="Image not found."), 404
    response = jsonify(image_data_url=to_data_url(*stored))
    response.headers["Cache-Control"] = "private, no-store"
    return response


@decks_bp.post("/decks/<deck_id>/diagrams/<item_id>/finalize")
@require_auth
def finalize_diagram(deck_id, item_id):
    """Persist the existing frontend autoDescribe result once, then enable its link."""
    _, item = owned_item(deck_id, item_id)
    if item.status == "ready":
        return jsonify(ok=True)
    if item.status != "awaiting_description":
        return jsonify(error="The diagram is not ready for descriptions yet."), 409
    record = Flowchart.query.filter_by(
        flowchart_id=item.flowchart_id, owner_id=g.user_id, deleted_at=None
    ).first()
    if not record:
        return jsonify(error="The diagram was removed."), 404
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify(error="Expected a JSON object."), 400
    if any(
        not isinstance(body.get(key), str) or not body[key].strip() or len(body[key]) > limit
        for key, limit in (("short_alt", 20000), ("summary", 200000))
    ):
        return jsonify(error="Provide a short description and a long description."), 400
    # A conditional update prevents duplicate finalization from overwriting edits in another tab.
    Flowchart.query.filter_by(
        flowchart_id=item.flowchart_id, owner_id=g.user_id, deleted_at=None, summary=None
    ).update(
        {
            "short_alt": body["short_alt"],
            "summary": body["summary"],
            "public_slug": uuid.uuid4().hex[:12],
            "is_published": True,
            "visibility": "private",
            "image_public": True,
            "published_at": datetime.datetime.utcnow(),
        },
        synchronize_session=False,
    )
    item.status = "ready"
    db.session.commit()
    return jsonify(ok=True)


@decks_bp.post("/decks/<deck_id>/retry")
@require_auth
def retry_deck(deck_id):
    deck = owned_deck(deck_id)
    changed = Job.query.filter(Job.id == deck.job_id, Job.status.in_(["done", "failed"])).update(
        {
            "status": "queued",
            "started_at": None,
            "finished_at": None,
            "error": None,
            "result": None,
        },
        synchronize_session=False,
    )
    db.session.commit()
    if not changed:
        return jsonify(error="This deck is already queued or processing."), 409
    return jsonify(ok=True)
