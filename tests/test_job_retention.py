"""Uploaded images must not stay in the jobs table.
    .venv/bin/python -m unittest tests.test_job_retention -v
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["AUTO_CREATE_TABLES"] = "1"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
os.environ.pop("K_SERVICE", None)

from backend.app_factory import create_app  # noqa: E402
from backend.db import db  # noqa: E402
from backend.jobs.retention import EMPTY_PAYLOAD, purge_job_images  # noqa: E402
from backend.jobs.worker import complete_job, fail_job  # noqa: E402
from backend.models import Job  # noqa: E402

IMG = "data:image/png;base64," + "A" * 200


def make(type_, status, age_hours, with_result=False, payload=None):
    j = Job(
        type=type_, status=status, owner_id="u",
        payload=payload if payload is not None else json.dumps({"image_b64": "A" * 200}),
        created_at=datetime.utcnow() - timedelta(hours=age_hours),
    )
    if with_result:
        j.result = json.dumps({"mermaid_json": {"nodes": []}, "image_data_url": IMG, "image_mime": "image/png"})
    db.session.add(j)
    db.session.commit()
    return j.id


class RetentionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        Job.query.delete()
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.ctx.pop()

    def test_completing_or_failing_empties_the_payload(self):
        for finish in (lambda j: complete_job(j, {"ok": True}), lambda j: fail_job(j, "no")):
            jid = make("process_upload", "running", 0)
            finish(db.session.get(Job, jid))
            self.assertEqual(db.session.get(Job, jid).payload, EMPTY_PAYLOAD)

    def test_other_job_types_keep_their_payload(self):
        jid = make("generate_summary", "running", 0, payload=json.dumps({"diagram": {"nodes": []}}))
        complete_job(db.session.get(Job, jid), {"ok": True})
        self.assertIn("diagram", db.session.get(Job, jid).payload)

    def test_old_results_lose_the_embedded_image_but_keep_the_rest(self):
        old = make("process_upload", "done", 5, with_result=True)
        new = make("process_upload", "done", 0, with_result=True)
        counts = purge_job_images(older_than_hours=1)
        self.assertEqual(counts["results"], 1)
        kept = json.loads(db.session.get(Job, old).result)
        self.assertNotIn("image_data_url", kept)
        self.assertIn("mermaid_json", kept)
        self.assertIn("image_data_url", json.loads(db.session.get(Job, new).result))

    def test_old_finished_inputs_are_emptied_and_recent_or_running_are_not(self):
        old_done = make("process_upload", "done", 5)
        recent_done = make("process_upload", "done", 0)
        old_running = make("extract_chart", "running", 5)
        abandoned = make("extract_chart", "queued", 30)
        purge_job_images(older_than_hours=1)
        pay = lambda i: db.session.get(Job, i).payload  # noqa: E731
        self.assertEqual(pay(old_done), EMPTY_PAYLOAD)
        self.assertNotEqual(pay(recent_done), EMPTY_PAYLOAD)
        self.assertNotEqual(pay(old_running), EMPTY_PAYLOAD)
        self.assertEqual(pay(abandoned), EMPTY_PAYLOAD)

    def test_dry_run_changes_nothing_and_a_second_run_finds_nothing(self):
        jid = make("process_upload", "done", 5, with_result=True)
        dry = purge_job_images(older_than_hours=1, dry_run=True)
        self.assertEqual(dry, {"payloads": 1, "results": 1})
        self.assertIn("image_data_url", db.session.get(Job, jid).result)
        purge_job_images(older_than_hours=1)
        self.assertEqual(purge_job_images(older_than_hours=1), {"payloads": 0, "results": 0})


if __name__ == "__main__":
    unittest.main()
