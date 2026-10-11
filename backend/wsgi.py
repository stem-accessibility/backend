"""WSGI entrypoint: `gunicorn backend.wsgi:app`.

Runs the job worker as a daemon thread inside the web process so a single
service handles both requests and queued jobs. Use exactly one gunicorn
worker process (threads are fine); set RUN_WORKER_IN_PROCESS=0 to disable
when running the worker as a separate service (`python -m backend.jobs.worker`).
"""

import os
import threading

from backend.app_factory import create_app

app = create_app()

if os.environ.get("RUN_WORKER_IN_PROCESS", "1") == "1":
    from backend.jobs.worker import run_worker_loop

    threading.Thread(
        target=run_worker_loop, args=(app,), daemon=True, name="job-worker"
    ).start()
