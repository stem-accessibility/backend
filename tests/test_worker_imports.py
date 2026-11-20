"""The worker must not load the image pipeline (torch, YOLO, Google Vision) just by being imported,
and `process_image` must stay available by name for job types that pass it along.
    .venv/bin/python -m unittest tests.test_worker_imports -v
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ["AUTH_MODE"] = "dev"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.sqlite"
os.environ.pop("K_SERVICE", None)

ROOT = Path(__file__).resolve().parent.parent


class WorkerImportTests(unittest.TestCase):
    def test_importing_the_worker_does_not_load_the_pipeline(self):
        # A fresh interpreter: other tests (test_job_retention) import the worker first, and a
        # cached module would pass this check whatever its imports are.
        check = textwrap.dedent(
            """
            import sys
            import backend.jobs.worker
            loaded = [m for m in ("backend.pipeline.pipeline2", "torch", "ultralytics", "google.cloud.vision")
                      if m in sys.modules]
            print(",".join(loaded))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", check],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "", "imported at module load: " + result.stdout.strip())

    def test_process_image_loads_the_pipeline_when_called(self):
        import backend.jobs.worker as worker

        calls = []
        fake = types.ModuleType("backend.pipeline.pipeline2")
        fake.process_image = lambda path, base_name=None: calls.append((path, base_name)) or {"nodes": [], "edges": []}
        with mock.patch.dict(sys.modules, {"backend.pipeline.pipeline2": fake}):
            self.assertEqual(worker.process_image("/tmp/x.png", base_name="uploaded"), {"nodes": [], "edges": []})
        self.assertEqual(calls, [("/tmp/x.png", "uploaded")])


if __name__ == "__main__":
    unittest.main()
