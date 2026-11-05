"""Checkpointed deck processing. Run with the existing single-worker queue."""

import json
import os
import tempfile
import uuid

from backend.db import db
from backend.image_store import get_store
from backend.models import DeckDiagram, Flowchart, SlideDeck
from backend.pipeline.deck_detection import (
    DeckError,
    crop_region,
    detect_regions,
    embedded_image_boxes,
    refine_regions,
    render_slide,
)


def process_deck(deck_id, process_image):
    """Keep successful crops/graphs on retry; never change completed descriptions."""
    deck = db.session.get(SlideDeck, deck_id)
    if deck is None:
        raise DeckError("The slide deck no longer exists.")
    pages = json.loads(deck.pages_json)
    for index, page_status in enumerate(pages):
        if page_status["status"] == "done":
            continue
        try:
            if not deck.pdf_data:
                raise DeckError("The source PDF is unavailable. Please upload it again.")
            image = render_slide(deck.pdf_data, index)
            try:
                regions = refine_regions(
                    detect_regions(image), embedded_image_boxes(deck.pdf_data, index)
                )
                for position, region in enumerate(regions, 1):
                    image_id = get_store().put(
                        deck.owner_id, crop_region(image, region["box_2d"]), "image/png"
                    )
                    db.session.add(
                        DeckDiagram(
                            deck_id=deck.id,
                            page_number=index + 1,
                            position=position,
                            title=region["name"],
                            kind=region["kind"],
                            box_json=json.dumps(region["box_2d"]),
                            image_id=image_id,
                            status="queued",
                        )
                    )
                pages[index] = {"status": "done", "count": len(regions)}
                deck.pages_json = json.dumps(pages)
                db.session.commit()  # Crops and the page checkpoint are atomic.
            finally:
                image.close()
        except Exception as exc:
            db.session.rollback()
            pages[index] = {
                "status": "failed",
                "error": (
                    str(exc)
                    if isinstance(exc, DeckError)
                    else "This slide could not be processed. Retry the deck."
                ),
            }
            deck.pages_json = json.dumps(pages)
            db.session.commit()

    # Once detection succeeds everywhere, retries only need crops, not the whole private PDF.
    if all(page["status"] == "done" for page in pages):
        deck.pdf_data = None
        db.session.commit()

    items = (
        DeckDiagram.query.filter_by(deck_id=deck.id)
        .order_by(DeckDiagram.page_number, DeckDiagram.position)
        .all()
    )
    for item in items:
        if item.status in ("ready", "awaiting_description"):
            continue
        item.status = "processing"
        item.error = None
        db.session.commit()
        tmp_path = None
        try:
            stored = get_store().get(item.image_id, deck.owner_id)
            if not stored:
                raise DeckError("The cropped image is missing. Please upload the deck again.")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(stored[0])
                tmp_path = tmp.name
            graph = process_image(tmp_path, base_name=f"deck_{item.id}")
            if not isinstance(graph, dict) or not graph.get("nodes"):
                raise DeckError("The existing diagram reader found no nodes in this image.")
            record = Flowchart(
                flowchart_id=str(uuid.uuid4()),
                owner_id=deck.owner_id,
                title=item.title,
                json_data=json.dumps(graph),
                flowchart_type="flowchart",
                image_id=item.image_id,
                image_mime="image/png",
                visibility="private",
                is_published=False,
                image_public=False,
            )
            db.session.add(record)
            item.flowchart_id = record.flowchart_id
            item.status = "awaiting_description"
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            item.status = "failed"
            item.error = (
                str(exc)
                if isinstance(exc, DeckError)
                else ("The existing image reader failed. Check OCR/AI credentials and retry.")
            )
            db.session.commit()
        finally:
            if tmp_path:
                os.unlink(tmp_path)

    return {"deck_id": deck.id}
