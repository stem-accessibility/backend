"""Deck tests use a fresh in-memory DB and fake AI/OCR; no credentials or network."""

import io
import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("AUTH_MODE", "dev")

import pypdfium2 as pdfium
from PIL import Image

from backend.app_factory import create_app
from backend.db import db
from backend.jobs.decks import process_deck
from backend.models import DeckDiagram, Flowchart, Job, SlideDeck, StemImage
from backend.pipeline.deck_detection import (
    DeckError,
    crop_region,
    detect_regions,
    inspect_pdf,
    embedded_image_boxes,
    refine_regions,
    validate_regions,
)

GRAPH = {
    "nodes": [
        {"id": "a", "label": "Start", "shape": "rectangle", "coordinates": [[0, 0], [100, 50]]}
    ],
    "edges": [],
}
REGION = {"name": "Example diagram", "kind": "flowchart", "box_2d": [100, 100, 900, 900]}


def pdf_bytes(pages=1):
    output = io.BytesIO()
    with pdfium.PdfDocument.new() as document:
        for _ in range(pages):
            document.new_page(640, 360).close()
        document.save(output)
    return output.getvalue()


class DetectionTests(unittest.TestCase):
    def test_pdf_validation(self):
        self.assertEqual(inspect_pdf(pdf_bytes(2)), 2)
        for data in (b"", b"not pdf", b"%PDF-broken", pdf_bytes(21)):
            with self.assertRaises(DeckError):
                inspect_pdf(data)

    def test_bounds_and_duplicates(self):
        self.assertEqual(len(validate_regions([REGION, REGION])), 1)
        self.assertEqual(validate_regions([]), [])
        for box in (
            [900, 0, 100, 2],
            [0, -1, 100, 100],
            [0, 0, 0, 5],
            [0, 0, float("nan"), 5],
            [False, 0, 2, 5],
            [0, 1],
        ):
            with self.assertRaises(DeckError):
                validate_regions([{**REGION, "box_2d": box}])
        with self.assertRaises(DeckError):
            validate_regions({"diagrams": []})

    def test_crop_preserves_pixels_and_coordinate_order(self):
        image = Image.new("RGB", (200, 100), (12, 34, 56))
        crop = Image.open(io.BytesIO(crop_region(image, [100, 200, 500, 800])))
        self.assertEqual(crop.size, (132, 52))
        self.assertEqual(crop.getpixel((5, 5)), (12, 34, 56))
        self.assertEqual(
            Image.open(io.BytesIO(crop_region(image, [0, 0, 1000, 1000]))).size, image.size
        )

    def test_embedded_image_boundary_refinement(self):
        self.assertEqual(embedded_image_boxes(pdf_bytes(), 0), [])
        image_box = [100, 100, 900, 900]
        partial = {**REGION, "box_2d": [150, 200, 800, 800]}
        self.assertEqual(refine_regions([partial], [image_box])[0]["box_2d"], image_box)
        self.assertEqual(refine_regions([partial], []), [partial])
        # Two figures inside one raster image must not become the same crop.
        separate = [
            {**REGION, "box_2d": [100, 100, 900, 500]},
            {**REGION, "box_2d": [100, 500, 900, 900]},
        ]
        self.assertEqual(refine_regions(separate, [image_box]), separate)

    @patch.dict(os.environ, {"GEMINI_API_KEY": "fake"})
    @patch("backend.pipeline.deck_detection.genai.Client")
    def test_sdk_structured_response(self, client):
        client.return_value.models.generate_content.return_value.text = json.dumps([REGION])
        self.assertEqual(detect_regions(Image.new("RGB", (20, 20))), [REGION])
        options = client.return_value.models.generate_content.call_args.kwargs
        self.assertEqual(options["config"].response_mime_type, "application/json")
        self.assertEqual(options["config"].thinking_config.thinking_budget, 0)
        client.return_value.models.generate_content.side_effect = RuntimeError("secret-key")
        with self.assertRaises(DeckError) as raised:
            detect_regions(Image.new("RGB", (20, 20)))
        self.assertNotIn("secret-key", str(raised.exception))
        quota_error = RuntimeError("secret-key")
        quota_error.code = 429
        client.return_value.models.generate_content.side_effect = quota_error
        with self.assertRaisesRegex(DeckError, "quota or rate limit"):
            detect_regions(Image.new("RGB", (20, 20)))


class DeckRouteTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_URL": "sqlite:///:memory:",
                "AUTO_CREATE_TABLES": "1",
                "GEMINI_API_KEY": "fake",
            },
        )
        self.env.start()
        self.app = create_app()
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        self.context.pop()
        self.env.stop()

    def upload(self, count=1):
        response = self.client.post(
            "/decks", data={"file": (io.BytesIO(pdf_bytes(count)), "test.pdf")}
        )
        self.assertEqual(response.status_code, 202, response.get_json())
        return response.get_json()["id"]

    def test_upload_validation(self):
        self.assertEqual(self.client.post("/decks").status_code, 400)
        response = self.client.post("/decks", data={"file": (io.BytesIO(b"fake"), "slides.pdf")})
        self.assertEqual(response.status_code, 400)
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            self.assertEqual(
                self.client.post(
                    "/decks", data={"file": (io.BytesIO(pdf_bytes()), "x.pdf")}
                ).status_code,
                503,
            )

    @patch("backend.jobs.decks.detect_regions", return_value=[REGION])
    def test_end_to_end_persistence_and_idempotent_finalize(self, detect):
        deck_id = self.upload()
        reader = Mock(return_value=GRAPH)
        process_deck(deck_id, reader)
        result = self.client.get(f"/decks/{deck_id}").get_json()
        item = result["items"][0]
        self.assertEqual(item["status"], "awaiting_description")
        self.assertIsNone(item["public_path"])
        self.assertIsNone(db.session.get(SlideDeck, deck_id).pdf_data)
        endpoint = f"/decks/{deck_id}/diagrams/{item['id']}/finalize"
        self.assertEqual(self.client.post(endpoint, json={}).status_code, 400)
        self.assertEqual(
            self.client.post(
                endpoint, json={"short_alt": "A start node.", "summary": "## Structure\nOne node."}
            ).status_code,
            200,
        )
        record = Flowchart.query.one()
        slug = record.public_slug
        self.assertTrue(record.image_public)
        self.assertEqual(record.visibility, "private")
        self.assertEqual(self.client.get(f"/p/{slug}").status_code, 200)
        self.assertEqual(self.client.get(f"/p/{slug}/image").status_code, 200)
        self.assertFalse(self.client.get("/repo").get_json())
        record.summary = "Instructor edit"
        db.session.commit()
        self.client.post(endpoint, json={"short_alt": "overwrite", "summary": "overwrite"})
        process_deck(deck_id, reader)
        db.session.expire_all()
        self.assertEqual(Flowchart.query.one().summary, "Instructor edit")
        self.assertEqual(Flowchart.query.one().public_slug, slug)
        self.assertEqual(StemImage.query.count(), 1)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(detect.call_count, 1)

    @patch("backend.jobs.decks.detect_regions")
    def test_multiple_diagrams_keep_slide_and_position(self, detect):
        deck_id = self.upload(2)
        detect.side_effect = [
            [
                {**REGION, "box_2d": [100, 100, 900, 450]},
                {**REGION, "name": "Second figure", "box_2d": [100, 550, 900, 900]},
            ],
            [],
        ]
        process_deck(deck_id, Mock(return_value=GRAPH))
        result = self.client.get(f"/decks/{deck_id}").get_json()
        self.assertEqual(
            [(item["page_number"], item["position"]) for item in result["items"]],
            [(1, 1), (1, 2)],
        )
        self.assertEqual(
            result["pages"], [{"status": "done", "count": 2}, {"status": "done", "count": 0}]
        )
        self.assertEqual(Flowchart.query.count(), 2)
        self.assertEqual(StemImage.query.count(), 2)

    @patch("backend.jobs.decks.detect_regions")
    def test_partial_failure_and_retry_without_duplicate_crops(self, detect):
        deck_id = self.upload(2)
        detect.side_effect = [[REGION], DeckError("Temporary detection failure")]
        reader = Mock(side_effect=RuntimeError("private detail"))
        process_deck(deck_id, reader)
        result = self.client.get(f"/decks/{deck_id}").get_json()
        self.assertEqual(result["pages"][1]["status"], "failed")
        self.assertNotIn("private detail", result["items"][0]["error"])
        detect.side_effect = [[]]
        reader.side_effect = None
        reader.return_value = GRAPH
        process_deck(deck_id, reader)
        self.assertEqual(DeckDiagram.query.count(), 1)
        self.assertEqual(StemImage.query.count(), 1)
        self.assertEqual(Flowchart.query.count(), 1)
        self.assertEqual(json.loads(db.session.get(SlideDeck, deck_id).pages_json)[1]["count"], 0)

    @patch("backend.jobs.decks.detect_regions", return_value=[REGION])
    def test_owner_isolation_and_retry_claim(self, _detect):
        deck_id = self.upload()
        process_deck(deck_id, Mock(return_value=GRAPH))
        item_id = DeckDiagram.query.one().id
        deck = db.session.get(SlideDeck, deck_id)
        job = db.session.get(Job, deck.job_id)
        self.assertEqual(self.client.post(f"/decks/{deck_id}/retry").status_code, 409)
        job.status = "done"
        db.session.commit()
        self.assertEqual(self.client.post(f"/decks/{deck_id}/retry").status_code, 200)
        self.assertEqual(self.client.post(f"/decks/{deck_id}/retry").status_code, 409)
        deck.owner_id = "another-user"
        db.session.commit()
        self.assertEqual(self.client.get("/decks").get_json(), [])
        for endpoint in (f"/decks/{deck_id}", f"/decks/{deck_id}/diagrams/{item_id}/image"):
            self.assertEqual(self.client.get(endpoint).status_code, 404)
        self.assertEqual(
            self.client.post(f"/decks/{deck_id}/diagrams/{item_id}/finalize", json={}).status_code,
            404,
        )


if __name__ == "__main__":
    unittest.main()
