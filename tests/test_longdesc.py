"""Long descriptions: the open /ld page saves one and anyone can read it by link.

Regression: POST /longdesc used to return 500 for every request because owner_id is NOT NULL and
was never set.

Runs against a throwaway SQLite file; never touches a real database.
    .venv/bin/python -m unittest tests.test_longdesc -v
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
from backend.guest import limiter  # noqa: E402
from backend.models import LongDescription  # noqa: E402

BODY = {"alt_text": "A bar chart of monthly rainfall.", "long_markdown": "# Rainfall\n\nWet in winter.", "title": "Rain"}


class LongDescTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.c = cls.app.test_client()
        assert cls.app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")  # never a real database

    def setUp(self):
        limiter.reset()

    def test_anonymous_save_works_and_round_trips(self):
        r = self.c.post("/longdesc", json=BODY)
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        slug = r.get_json()["id"]
        got = self.c.get(f"/longdesc/{slug}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["long_markdown"], BODY["long_markdown"])
        with self.app.app_context():
            self.assertEqual(LongDescription.query.filter_by(slug=slug).one().owner_id, "anonymous")

    def test_custom_slug_and_duplicate(self):
        self.assertEqual(self.c.post("/longdesc", json={**BODY, "slug": "my-chart_1"}).status_code, 201)
        r = self.c.post("/longdesc", json={**BODY, "slug": "my-chart_1"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("already exists", r.get_json()["error"])

    def test_rejects_bad_input_with_a_400(self):
        bad = [
            {},
            {"alt_text": "x"},
            {**BODY, "slug": "a b"},
            {**BODY, "slug": "x"},
            {**BODY, "alt_text": 5},
            {**BODY, "alt_text": "x" * 2001},
            {**BODY, "long_markdown": "x" * 50_001},
            {**BODY, "title": "x" * 256},
            {**BODY, "image_data_url": "https://example.com/x.png"},
            {**BODY, "image_data_url": "data:image/png;base64," + "A" * 5_000_000},
        ]
        for b in bad:
            with self.subTest(str(b)[:50]):
                self.assertEqual(self.c.post("/longdesc", json=b).status_code, 400)

    def test_accepts_an_image(self):
        r = self.c.post("/longdesc", json={**BODY, "image_data_url": "data:image/png;base64,iVBORw0KGgo="})
        self.assertEqual(r.status_code, 201)

    def test_is_rate_limited_per_address(self):
        codes = [self.c.post("/longdesc", json=BODY).status_code for _ in range(31)]
        self.assertEqual(codes[:30], [201] * 30)
        self.assertEqual(codes[30], 429)

    def test_missing_slug_is_404_without_internals(self):
        r = self.c.get("/longdesc/nope")
        self.assertEqual(r.status_code, 404)

    def test_server_errors_do_not_leak_internals(self):
        # Force a failure after validation by making the table unavailable for the insert.
        from backend.db import db
        with self.app.app_context():
            db.session.execute(db.text("alter table long_descriptions rename to ld_tmp"))
            db.session.commit()
        try:
            r = self.c.post("/longdesc", json=BODY)
            self.assertEqual(r.status_code, 500)
            self.assertEqual(r.get_json(), {"error": "Internal Server Error"})
        finally:
            with self.app.app_context():
                db.session.rollback()
                db.session.execute(db.text("alter table ld_tmp rename to long_descriptions"))
                db.session.commit()


if __name__ == "__main__":
    unittest.main()
