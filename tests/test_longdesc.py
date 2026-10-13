"""Long descriptions: the open /ld page saves one and anyone can read it by link.

Regression: POST /longdesc used to return 500 for every request because owner_id is NOT NULL and
was never set.

Runs against a throwaway SQLite file; never touches a real database.
    .venv/bin/python -m unittest tests.test_longdesc -v
"""
import os
import tempfile
import unittest
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTO_CREATE_TABLES"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
os.environ.pop("K_SERVICE", None)

from backend.app_factory import create_app  # noqa: E402
from backend import auth as auth_module  # noqa: E402
from backend.guest import client_ip, limiter  # noqa: E402
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


IMG = "data:image/png;base64,iVBORw0KGgo="


def _signed_in_as(user_id):
    """Pretend a valid Supabase token for `user_id` was sent (no network, no real keys)."""
    fake_jwks = mock.MagicMock()
    return [
        mock.patch.object(auth_module, "DEV_AUTH", False),
        mock.patch.object(auth_module, "_jwk_client", fake_jwks),
        mock.patch.object(auth_module.jwt, "get_unverified_header", return_value={"alg": "ES256"}),
        mock.patch.object(auth_module.jwt, "decode", return_value={"sub": user_id, "email": "a@b.c"}),
    ]


class ClientAddressTests(unittest.TestCase):
    """Rate limits are only as good as the address they key on."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def ip(self, xff, env=None):
        env = env or {}
        with mock.patch.dict(os.environ, env, clear=False), self.app.test_request_context(
            "/", headers={"X-Forwarded-For": xff}, environ_base={"REMOTE_ADDR": "9.9.9.9"}
        ):
            return client_ip()

    def test_header_is_ignored_when_no_proxy_is_trusted(self):
        # Running locally or anywhere without a known proxy: the header is just caller-typed text.
        self.assertEqual(self.ip("1.2.3.4"), "9.9.9.9")

    def test_on_cloud_run_the_address_the_platform_appended_is_used(self):
        # Caller wrote "6.6.6.6, 7.7.7.7"; Cloud Run appended the address it really saw.
        self.assertEqual(self.ip("6.6.6.6, 7.7.7.7, 34.1.2.3", {"K_SERVICE": "svc"}), "34.1.2.3")

    def test_an_extra_trusted_hop_is_counted_from_the_right(self):
        self.assertEqual(self.ip("6.6.6.6, 34.1.2.3, 130.211.0.1", {"TRUSTED_PROXY_HOPS": "2"}), "34.1.2.3")

    def test_a_short_header_falls_back_to_the_connection_address(self):
        self.assertEqual(self.ip("", {"K_SERVICE": "svc"}), "9.9.9.9")
        self.assertEqual(self.ip("34.1.2.3", {"TRUSTED_PROXY_HOPS": "3"}), "9.9.9.9")


class LongDescAbuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.c = cls.app.test_client()
        assert cls.app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")

    def setUp(self):
        limiter.reset()

    def post(self, body=None, headers=None):
        return self.c.post("/longdesc", json=body or BODY, headers=headers or {})

    # --- the forged-header bypass ---------------------------------------------------------------

    def test_forged_forwarded_for_cannot_dodge_the_limit_on_cloud_run(self):
        env = {"K_SERVICE": "svc"}
        with mock.patch.dict(os.environ, env):
            codes = [
                self.post(headers={"X-Forwarded-For": f"10.0.{i}.1, 34.1.2.3"}).status_code
                for i in range(31)
            ]
        self.assertEqual(codes[:30], [201] * 30)
        self.assertEqual(codes[30], 429)   # every one of them came from 34.1.2.3

    def test_a_different_real_caller_is_not_blocked_by_someone_else(self):
        with mock.patch.dict(os.environ, {"K_SERVICE": "svc"}):
            for _ in range(30):
                self.post(headers={"X-Forwarded-For": "34.1.2.3"})
            self.assertEqual(self.post(headers={"X-Forwarded-For": "34.1.2.3"}).status_code, 429)
            self.assertEqual(self.post(headers={"X-Forwarded-For": "52.9.9.9"}).status_code, 201)

    def test_header_is_not_trusted_at_all_without_a_proxy(self):
        codes = [self.post(headers={"X-Forwarded-For": f"10.1.{i}.1"}).status_code for i in range(31)]
        self.assertEqual(codes.count(429), 1)

    # --- images need an account -----------------------------------------------------------------

    def test_an_image_without_sign_in_is_refused_and_nothing_is_stored(self):
        with mock.patch.object(auth_module, "DEV_AUTH", False):
            r = self.post({**BODY, "slug": "no-login-img", "image_data_url": IMG})
        self.assertEqual(r.status_code, 401)
        self.assertIn("Sign in", r.get_json()["error"])
        with self.app.app_context():
            self.assertIsNone(LongDescription.query.filter_by(slug="no-login-img").first())

    def test_a_bad_token_counts_as_not_signed_in(self):
        with mock.patch.object(auth_module, "DEV_AUTH", False), mock.patch.object(
            auth_module, "_jwk_client", None
        ):
            r = self.post({**BODY, "image_data_url": IMG}, headers={"Authorization": "Bearer nonsense"})
        self.assertEqual(r.status_code, 401)

    def test_text_only_still_works_without_an_account(self):
        with mock.patch.object(auth_module, "DEV_AUTH", False):
            r = self.post({**BODY, "slug": "text-only-ok"})
        self.assertEqual(r.status_code, 201)
        with self.app.app_context():
            self.assertEqual(LongDescription.query.filter_by(slug="text-only-ok").one().owner_id, "anonymous")

    def test_a_signed_in_user_can_save_an_image_and_owns_it(self):
        patches = _signed_in_as("user-123")
        for p in patches:
            p.start()
        try:
            r = self.post({**BODY, "slug": "with-image-ok", "image_data_url": IMG},
                          headers={"Authorization": "Bearer fake"})
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(LongDescription.query.filter_by(slug="with-image-ok").one().owner_id, "user-123")

    def test_image_saves_are_limited_per_account(self):
        patches = _signed_in_as("user-limited")
        for p in patches:
            p.start()
        try:
            with mock.patch("backend.routes.api.LONGDESC_IMAGES_PER_USER_PER_HOUR", 2):
                codes = [self.post({**BODY, "image_data_url": IMG}, headers={"Authorization": "Bearer f"}).status_code
                         for _ in range(3)]
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(codes, [201, 201, 429])

    def test_an_account_can_only_keep_so_many_images(self):
        patches = _signed_in_as("user-capped")
        for p in patches:
            p.start()
        try:
            with mock.patch("backend.routes.api.LONGDESC_MAX_IMAGES_PER_USER", 2):
                codes = [self.post({**BODY, "image_data_url": IMG}, headers={"Authorization": "Bearer f"}).status_code
                         for _ in range(3)]
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(codes, [201, 201, 409])


class LegacyRoutesAreGoneTests(unittest.TestCase):
    """/upload, /generate-summary and /generate-outline were open to anyone, ran the paid image
    pipeline and an LLM with no sign-in or limit, and nothing in the app called them (it uses the
    signed-in /jobs/process-upload and /jobs/generate-summary). They were removed, not just gated."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.c = cls.app.test_client()

    def test_removed_routes_do_not_exist(self):
        for path in ("/upload", "/generate-summary", "/generate-outline"):
            with self.subTest(path):
                self.assertEqual(self.c.post(path, json={"diagram": {"nodes": [], "edges": []}}).status_code, 404)

    def test_the_signed_in_job_routes_that_replace_them_still_exist(self):
        rules = {r.rule for r in self.app.url_map.iter_rules()}
        self.assertIn("/jobs/process-upload", rules)
        self.assertIn("/jobs/generate-summary", rules)


if __name__ == "__main__":
    unittest.main()
