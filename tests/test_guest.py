"""Try-it (guest) flow: one public image per browser token, no account, strict limits.

Runs against a throwaway SQLite file with dev auth; never touches a real database.
    .venv/bin/python -m unittest tests.test_guest -v
"""
import os
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTO_CREATE_TABLES"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/guest.sqlite"
os.environ.pop("K_SERVICE", None)

from backend import guest as guest_mod  # noqa: E402
from backend.app_factory import create_app  # noqa: E402

TOKEN_A = "a" * 40
TOKEN_B = "b" * 40
GRAPH = {
    "nodes": [
        {"id": "A", "label": "Start", "shape": "rectangle", "coordinates": [[0, 0], [100, 50]]},
        {"id": "B", "label": "End", "shape": "rectangle", "coordinates": [[0, 100], [100, 150]]},
    ],
    "edges": [{"id": "e1", "source": "A", "destination": "B"}],
}


def body(**extra):
    return {"json_data": GRAPH, "title": "My try", "short_alt": "alt", "summary": "## Purpose\nx", **extra}


class GuestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.c = cls.app.test_client()
        assert cls.app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")  # never a real database

    def setUp(self):
        guest_mod.limiter.reset()

    def h(self, token=TOKEN_A):
        return {"X-Guest-Token": token}

    def test_needs_a_valid_token(self):
        self.assertEqual(self.c.get("/guest/image").status_code, 400)
        self.assertEqual(self.c.get("/guest/image", headers={"X-Guest-Token": "short"}).status_code, 400)
        self.assertEqual(self.c.get("/guest/image", headers={"X-Guest-Token": "bad token!" * 5}).status_code, 400)

    def test_no_image_yet_then_create_public(self):
        h = self.h("c" * 40)
        self.assertIsNone(self.c.get("/guest/image", headers=h).get_json())
        r = self.c.put("/guest/image", json=body(), headers=h)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        d = r.get_json()
        self.assertEqual(d["sharing"], "public")
        self.assertTrue(d["guest"])
        self.assertFalse(d["has_image"])
        self.assertIn(d["flowchart_id"], {x["flowchart_id"] for x in self.c.get("/repo").get_json()})
        self.assertEqual(self.c.get(f"/p/{d['public_slug']}").status_code, 200)

    def test_one_image_per_token_updates_in_place(self):
        h = self.h("d" * 40)
        first = self.c.put("/guest/image", json=body(title="One"), headers=h).get_json()
        second = self.c.put("/guest/image", json=body(title="Two"), headers=h)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["flowchart_id"], first["flowchart_id"])
        self.assertEqual(self.c.get("/guest/image", headers=h).get_json()["title"], "Two")

    def test_tokens_are_isolated(self):
        a = self.c.put("/guest/image", json=body(title="Mine A"), headers=self.h("e" * 40)).get_json()
        b = self.c.put("/guest/image", json=body(title="Mine B"), headers=self.h("f" * 40)).get_json()
        self.assertNotEqual(a["flowchart_id"], b["flowchart_id"])
        self.assertEqual(self.c.get("/guest/image", headers=self.h("e" * 40)).get_json()["title"], "Mine A")

    def test_guest_cannot_choose_private_or_attach_an_image(self):
        h = self.h("g" * 40)
        d = self.c.put(
            "/guest/image",
            json=body(sharing="private", image_data_url="data:image/png;base64,AAAA", image_public=True),
            headers=h,
        ).get_json()
        self.assertEqual(d["sharing"], "public")
        self.assertFalse(d["has_image"])
        self.assertFalse(d["image_public"])

    def test_size_and_shape_limits(self):
        h = self.h("h" * 40)
        big = {"nodes": [{"id": str(i), "label": "x"} for i in range(guest_mod.MAX_NODES + 1)], "edges": []}
        self.assertEqual(self.c.put("/guest/image", json=body(json_data=big), headers=h).status_code, 400)
        long_label = {"nodes": [{"id": "A", "label": "x" * (guest_mod.MAX_LABEL + 1)}], "edges": []}
        self.assertEqual(self.c.put("/guest/image", json=body(json_data=long_label), headers=h).status_code, 400)
        self.assertEqual(self.c.put("/guest/image", json=body(title="t" * 500), headers=h).status_code, 400)
        self.assertEqual(self.c.put("/guest/image", json={"json_data": "nope"}, headers=h).status_code, 400)

    def test_rate_limit(self):
        h = self.h("i" * 40)
        codes = [self.c.put("/guest/image", json=body(), headers=h).status_code for _ in range(guest_mod.LIMIT_PER_TOKEN + 3)]
        self.assertEqual(codes[0], 201)
        self.assertEqual(codes[-1], 429)

    def test_delete_frees_the_slot_and_unlists(self):
        h = self.h("j" * 40)
        d = self.c.put("/guest/image", json=body(), headers=h).get_json()
        self.assertTrue(self.c.delete("/guest/image", headers=h).get_json()["deleted"])
        self.assertIsNone(self.c.get("/guest/image", headers=h).get_json())
        self.assertNotIn(d["flowchart_id"], {x["flowchart_id"] for x in self.c.get("/repo").get_json()})
        again = self.c.put("/guest/image", json=body(), headers=h)
        self.assertEqual(again.status_code, 201)
        self.assertNotEqual(again.get_json()["flowchart_id"], d["flowchart_id"])

    def test_claim_moves_it_into_the_account(self):
        h = self.h("k" * 40)
        d = self.c.put("/guest/image", json=body(title="Claim me"), headers=h).get_json()
        r = self.c.post("/guest/claim", headers=h)  # dev auth is the signed-in user
        self.assertTrue(r.get_json()["claimed"])
        mine = {x["flowchart_id"]: x for x in self.c.get("/flowcharts").get_json()}
        self.assertIn(d["flowchart_id"], mine)
        self.assertFalse(mine[d["flowchart_id"]]["guest"])
        self.assertIsNone(self.c.get("/guest/image", headers=h).get_json())
        self.assertFalse(self.c.post("/guest/claim", headers=h).get_json()["claimed"])

    def test_report_and_takedown(self):
        h = self.h("l" * 40)
        d = self.c.put("/guest/image", json=body(title="Spam"), headers=h).get_json()
        slug = d["public_slug"]
        self.assertEqual(self.c.post(f"/p/{slug}/report", json={"reason": "spam"}).status_code, 201)
        self.assertEqual(self.c.post("/p/not-a-real-slug/report", json={}).status_code, 404)
        runner = self.app.test_cli_runner()
        out = runner.invoke(args=["takedown", slug])
        self.assertIn("Took down", out.output)
        self.assertEqual(self.c.get(f"/p/{slug}").status_code, 404)
        self.assertNotIn(d["flowchart_id"], {x["flowchart_id"] for x in self.c.get("/repo").get_json()})

    def test_report_is_rate_limited(self):
        h = self.h("m" * 40)
        slug = self.c.put("/guest/image", json=body(), headers=h).get_json()["public_slug"]
        codes = [self.c.post(f"/p/{slug}/report", json={}).status_code for _ in range(guest_mod.LIMIT_REPORTS_PER_IP + 2)]
        self.assertEqual(codes[-1], 429)


if __name__ == "__main__":
    unittest.main()
