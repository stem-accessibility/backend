"""Originals live in stem_images, behind backend.image_store, and are removed with their STEM image.
    .venv/bin/python -m unittest tests.test_image_store -v
"""
import base64
import os
import tempfile
import unittest
import unittest.mock

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTO_CREATE_TABLES"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
os.environ.pop("K_SERVICE", None)

from backend.app_factory import create_app  # noqa: E402
from backend.db import db  # noqa: E402
from backend.image_store import (  # noqa: E402
    ImageError,
    get_store,
    migrate_legacy_images,
    parse_data_url,
    to_data_url,
)
from backend.image_store import set_flowchart_image  # noqa: E402
from backend.models import Flowchart, LongDescription, StemImage  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
URL = to_data_url(PNG, "image/png")
GRAPH = {"nodes": [], "edges": []}


class ParseTests(unittest.TestCase):
    def test_round_trip(self):
        data, mime = parse_data_url(URL)
        self.assertEqual((data, mime), (PNG, "image/png"))

    def test_rejects_bad_input(self):
        bad = [None, 5, "", "data:text/html;base64,PGI+", "data:image/png;base64,!!!",
               "data:image/png;base64,", "https://example.com/a.png"]
        for b in bad:
            with self.subTest(b=str(b)[:30]), self.assertRaises(ImageError):
                parse_data_url(b)

    def test_size_cap(self):
        big = to_data_url(b"x" * 20, "image/png")
        with unittest.mock.patch("backend.image_store.MAX_IMAGE_BYTES", 10):
            with self.assertRaises(ImageError):
                parse_data_url(big)


class _Fixture(unittest.TestCase):
    """App, throwaway database and helpers shared by the route tests. Has no tests of its own."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.client = cls.app.test_client()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        Flowchart.query.delete()
        LongDescription.query.delete()
        StemImage.query.delete()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def create(self, **extra):
        body = {"json_data": GRAPH, "summary": "s", **extra}
        r = self.client.post("/flowcharts", json=body)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["flowchart_id"]

    def row(self, fid):
        return Flowchart.query.filter_by(flowchart_id=fid).first()

class StoreAndRouteTests(_Fixture):
    def test_create_keeps_the_image_in_the_store_not_on_the_row(self):
        fid = self.create(image_data_url=URL)
        r = self.row(fid)
        self.assertIsNone(r.image_data_url)
        self.assertEqual(r.image_mime, "image/png")
        self.assertEqual(StemImage.query.count(), 1)
        got = self.client.get(f"/get/{fid}/image")
        self.assertEqual(got.get_json()["image_data_url"], URL)

    def test_listing_reports_has_image(self):
        fid = self.create(image_data_url=URL)
        data = self.client.get(f"/get/{fid}").get_json()
        self.assertTrue(data["has_image"])
        self.assertEqual(data["image_endpoint"], f"/get/{fid}/image")

    def test_bad_image_is_a_400_and_stores_nothing(self):
        r = self.client.post("/flowcharts", json={"json_data": GRAPH, "image_data_url": "data:text/html;base64,PGI+"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(StemImage.query.count(), 0)
        self.assertEqual(Flowchart.query.count(), 0)

    def test_replacing_removes_the_old_bytes(self):
        fid = self.create(image_data_url=URL)
        other = to_data_url(PNG + b"2", "image/png")
        r = self.client.put(f"/flowcharts/{fid}", json={"image_data_url": other})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(StemImage.query.count(), 1)
        self.assertEqual(self.client.get(f"/get/{fid}/image").get_json()["image_data_url"], other)

    def test_removing_only_the_image_keeps_the_stem_image(self):
        fid = self.create(image_data_url=URL)
        r = self.client.delete(f"/flowcharts/{fid}/image")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["has_image"])
        self.assertEqual(StemImage.query.count(), 0)
        self.assertEqual(self.client.get(f"/get/{fid}").status_code, 200)
        self.assertEqual(self.client.get(f"/get/{fid}/image").status_code, 404)

    def test_deleting_the_stem_image_deletes_the_original(self):
        fid = self.create(image_data_url=URL)
        self.assertEqual(self.client.delete(f"/flowcharts/{fid}").status_code, 200)
        self.assertEqual(StemImage.query.count(), 0)

    def test_public_image_only_when_the_owner_shared_it(self):
        fid = self.create(image_data_url=URL, sharing="link")
        slug = self.row(fid).public_slug
        self.assertEqual(self.client.get(f"/p/{slug}/image").status_code, 404)
        self.client.put(f"/flowcharts/{fid}/sharing", json={"sharing": "link", "image_public": True})
        self.assertEqual(self.client.get(f"/p/{slug}/image").get_json()["image_data_url"], URL)

    def test_store_scopes_reads_to_the_owner(self):
        fid = self.create(image_data_url=URL)
        r = self.row(fid)
        store = get_store()
        self.assertIsNotNone(store.get(r.image_id, owner_id=r.owner_id))
        self.assertIsNone(store.get(r.image_id, owner_id="someone-else"))

    def test_migration_moves_legacy_inline_images_and_is_idempotent(self):
        fid = self.create()
        r = self.row(fid)
        r.image_data_url, r.image_mime = URL, "image/png"
        broken = Flowchart(flowchart_id="broken", owner_id="u", json_data="{}", image_data_url="not an image")
        db.session.add(broken)
        db.session.commit()

        self.assertEqual(migrate_legacy_images(dry_run=True), {"moved": 1, "skipped_unreadable": 1})
        self.assertEqual(StemImage.query.count(), 0)
        self.assertEqual(migrate_legacy_images(), {"moved": 1, "skipped_unreadable": 1})
        r = self.row(fid)
        self.assertIsNone(r.image_data_url)
        self.assertIsNotNone(r.image_id)
        self.assertEqual(self.client.get(f"/get/{fid}/image").get_json()["image_data_url"], URL)
        self.assertEqual(migrate_legacy_images(), {"moved": 0, "skipped_unreadable": 1})


class LongDescriptionTests(_Fixture):
    """The /ld page uses the same store, so it keeps no inline copy of its own."""

    def owner(self):
        return self.client.get("/whoami").get_json()["user_id"]

    def make(self, slug, owner, image=URL, public=False):
        rec = LongDescription(slug=slug, owner_id=owner, alt_text="a", long_markdown="m",
                              image_public=public)
        set_flowchart_image(rec, image)
        db.session.add(rec)
        db.session.commit()
        return rec

    def test_image_is_in_the_store_and_served_unchanged(self):
        rec = self.make("ld-one", self.owner())
        self.assertIsNone(rec.image_data_url)
        self.assertEqual(StemImage.query.count(), 1)
        got = self.client.get("/longdesc/ld-one").get_json()
        self.assertEqual(got["image_data_url"], URL)

    def test_image_is_hidden_from_visitors_unless_the_author_shows_it(self):
        self.make("ld-private", "someone-else", public=False)
        self.make("ld-shown", "someone-else", public=True)
        hidden = self.client.get("/longdesc/ld-private").get_json()
        self.assertIsNone(hidden["image_data_url"])
        self.assertTrue(hidden["has_image"])
        self.assertFalse(hidden["image_public"])
        self.assertEqual(self.client.get("/longdesc/ld-shown").get_json()["image_data_url"], URL)

    def test_the_owner_always_sees_their_own_image(self):
        self.make("ld-mine", self.owner(), public=False)
        self.assertEqual(self.client.get("/longdesc/ld-mine").get_json()["image_data_url"], URL)

    def test_new_entries_default_to_private_and_can_opt_in(self):
        body = {"alt_text": "a", "long_markdown": "m", "image_data_url": URL}
        r = self.client.post("/longdesc", json={**body, "slug": "ld-new-default"})
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        self.assertFalse(r.get_json()["image_public"])
        r = self.client.post("/longdesc", json={**body, "slug": "ld-new-shown", "image_public": True})
        self.assertTrue(r.get_json()["image_public"])
        r = self.client.post("/longdesc", json={**body, "slug": "ld-new-bad", "image_public": "yes"})
        self.assertEqual(r.status_code, 400)

    def test_only_the_owner_can_change_whether_the_image_is_shown(self):
        self.make("ld-flip", self.owner(), public=False)
        self.make("ld-other", "someone-else", public=False)
        ok = self.client.put("/longdesc/ld-flip/sharing", json={"image_public": True})
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(LongDescription.query.filter_by(slug="ld-flip").first().image_public)
        self.assertEqual(self.client.put("/longdesc/ld-other/sharing", json={"image_public": True}).status_code, 404)
        self.assertEqual(self.client.put("/longdesc/ld-flip/sharing", json={"image_public": "yes"}).status_code, 400)

    def test_owner_can_delete_and_the_bytes_go_with_it(self):
        self.make("ld-two", self.owner())
        r = self.client.delete("/longdesc/ld-two")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(StemImage.query.count(), 0)
        self.assertEqual(self.client.get("/longdesc/ld-two").status_code, 404)

    def test_others_and_anonymous_entries_cannot_be_deleted(self):
        self.make("ld-theirs", "someone-else")
        self.make("ld-anon", "anonymous", image=None)
        self.assertEqual(self.client.delete("/longdesc/ld-theirs").status_code, 404)
        self.assertEqual(self.client.delete("/longdesc/ld-anon").status_code, 404)
        self.assertEqual(self.client.get("/longdesc/ld-theirs").status_code, 200)
        self.assertEqual(StemImage.query.count(), 1)

    def test_migration_covers_long_descriptions(self):
        # A row from before image_public existed: the migration sets those to true.
        rec = LongDescription(slug="ld-old", owner_id="u", alt_text="a", long_markdown="m",
                              image_data_url=URL, image_public=True)
        db.session.add(rec)
        db.session.commit()
        self.assertEqual(migrate_legacy_images(), {"moved": 1, "skipped_unreadable": 0})
        rec = LongDescription.query.filter_by(slug="ld-old").first()
        self.assertIsNone(rec.image_data_url)
        self.assertEqual(self.client.get("/longdesc/ld-old").get_json()["image_data_url"], URL)


if __name__ == "__main__":
    unittest.main()
