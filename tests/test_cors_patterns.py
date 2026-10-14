"""CORS origin patterns: wildcard hostnames for preview deployments, and refusal of unsafe patterns.
    .venv/bin/python -m unittest tests.test_cors_patterns -v
"""
import os
import tempfile
import unittest

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTO_CREATE_TABLES"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
os.environ.pop("K_SERVICE", None)

from backend.app_factory import cors_origin_patterns  # noqa: E402


def allowed(patterns, origin):
    return any(r.match(origin) for r in cors_origin_patterns(patterns))


P = "https://frontend-git-*-stem-accessibility.vercel.app"


class CorsPatternTests(unittest.TestCase):
    def test_matches_preview_hostnames(self):
        self.assertTrue(allowed(P, "https://frontend-git-main-stem-accessibility.vercel.app"))
        self.assertTrue(allowed(P, "https://frontend-git-feature-x-1-stem-accessibility.vercel.app"))

    def test_does_not_match_other_hosts(self):
        for origin in (
            "https://frontend-git-main-stem-accessibility.vercel.app.evil.com",
            "https://evil.com/frontend-git-main-stem-accessibility.vercel.app",
            "http://frontend-git-main-stem-accessibility.vercel.app",
            "https://frontend-git-a.b-stem-accessibility.vercel.app",
            "https://xfrontend-git-main-stem-accessibility.vercel.app",
            "https://frontend-git--stem-accessibility.vercel.app",
        ):
            with self.subTest(origin=origin):
                self.assertFalse(allowed(P, origin))

    def test_unsafe_patterns_are_ignored(self):
        for bad in ("*", "https://*", "https://*.com/x", "http://a-*.vercel.app", "https://a-*", ""):
            with self.subTest(pattern=bad):
                self.assertEqual(cors_origin_patterns(bad), [])

    def test_several_patterns(self):
        both = f"{P}, https://admin-*.example.org"
        self.assertTrue(allowed(both, "https://admin-1.example.org"))
        self.assertTrue(allowed(both, "https://frontend-git-main-stem-accessibility.vercel.app"))


if __name__ == "__main__":
    unittest.main()
