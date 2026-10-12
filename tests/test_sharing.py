"""Sharing model: one setting (public / link / private) that keeps visibility and
publication in sync, and an opt-in switch for the source image.

Runs against a throwaway SQLite file with dev auth; never touches a real database.
    .venv/bin/python -m unittest tests.test_sharing -v
"""
import os
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTO_CREATE_TABLES"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
os.environ.pop("K_SERVICE", None)

from backend.app_factory import create_app  # noqa: E402

IMG = "data:image/png;base64,iVBORw0KGgo="


class SharingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.c = cls.app.test_client()
        assert cls.app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")  # never a real database

    def make(self, **extra):
        body = {"json_data": {"nodes": [], "edges": []}, "title": "t", "image_data_url": IMG,
                "image_mime": "image/png", **extra}
        r = self.c.post("/flowcharts", json=body)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()

    def share(self, fid, sharing, **extra):
        return self.c.put(f"/flowcharts/{fid}/sharing", json={"sharing": sharing, **extra})

    def listed(self):
        return {x["flowchart_id"] for x in self.c.get("/repo").get_json()}

    def test_defaults_are_private_and_image_not_shared(self):
        d = self.make()
        self.assertEqual(d["sharing"], "private")
        self.assertFalse(d["is_published"])
        self.assertFalse(d["image_public"])

    def test_create_public_is_live_without_a_second_step(self):
        d = self.make(sharing="public")
        self.assertEqual(d["sharing"], "public")
        self.assertTrue(d["is_published"])
        self.assertIn(d["flowchart_id"], self.listed())
        self.assertEqual(self.c.get(f"/p/{d['public_slug']}").status_code, 200)

    def test_legacy_visibility_public_on_create_also_publishes(self):
        d = self.make(visibility="public")
        self.assertEqual(d["sharing"], "public")
        self.assertIn(d["flowchart_id"], self.listed())

    def test_link_only_has_page_but_is_not_listed(self):
        d = self.make()
        r = self.share(d["flowchart_id"], "link").get_json()
        self.assertEqual(r["sharing"], "link")
        self.assertEqual(r["public_url"], f"/p/{r['public_slug']}")
        self.assertNotIn(d["flowchart_id"], self.listed())
        self.assertEqual(self.c.get(f"/p/{r['public_slug']}").status_code, 200)

    def test_private_unpublishes_and_keeps_slug(self):
        d = self.make(sharing="public")
        slug = d["public_slug"]
        r = self.share(d["flowchart_id"], "private").get_json()
        self.assertEqual(r["sharing"], "private")
        self.assertEqual(self.c.get(f"/p/{slug}").status_code, 404)
        self.assertNotIn(d["flowchart_id"], self.listed())
        again = self.share(d["flowchart_id"], "public").get_json()
        self.assertEqual(again["public_slug"], slug)

    def test_source_image_is_hidden_until_the_owner_opts_in(self):
        d = self.make(sharing="public")
        slug, fid = d["public_slug"], d["flowchart_id"]
        self.assertFalse(self.c.get(f"/p/{slug}").get_json()["has_image"])
        self.assertEqual(self.c.get(f"/p/{slug}/image").status_code, 404)
        self.assertTrue(self.c.get(f"/get/{fid}").get_json()["has_image"])  # owner still sees it
        self.share(fid, "public", image_public=True)
        self.assertTrue(self.c.get(f"/p/{slug}").get_json()["has_image"])
        self.assertEqual(self.c.get(f"/p/{slug}/image").status_code, 200)
        self.share(fid, "public", image_public=False)
        self.assertEqual(self.c.get(f"/p/{slug}/image").status_code, 404)

    def test_legacy_endpoints_cannot_create_public_but_unpublished(self):
        d = self.make()
        fid = d["flowchart_id"]
        r = self.c.post(f"/research/{fid}", json={"visibility": "public"}).get_json()
        self.assertEqual(r["sharing"], "public")
        self.assertIn(fid, self.listed())
        r = self.c.post(f"/publish/{fid}", json={"publish": False}).get_json()
        self.assertFalse(r["is_published"])
        self.assertEqual(self.c.get(f"/get/{fid}").get_json()["sharing"], "private")

    def test_validation(self):
        d = self.make()
        self.assertEqual(self.share(d["flowchart_id"], "banana").status_code, 400)
        self.assertEqual(self.share(d["flowchart_id"], "public", image_public="yes").status_code, 400)
        bad = self.c.post("/flowcharts", json={"json_data": {}, "sharing": "banana"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.share("does-not-exist", "public").status_code, 404)


if __name__ == "__main__":
    unittest.main()
