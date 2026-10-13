"""Keep uploaded images out of the jobs table.

Image jobs carry the uploaded image twice: as `payload.image_b64` (the input) and, for the
flowchart upload, as `result.image_data_url` (so the page can show the original next to the
extracted structure). Neither is needed once the page has the result, so:

  * the payload is emptied the moment a job finishes or fails (worker.complete_job / fail_job);
  * `image_data_url` is stripped from results after JOB_IMAGE_TTL_HOURS (default 1), which is long
    enough for the page that started the job to read it;
  * jobs that never ran are emptied after ABANDONED_HOURS.

`purge_job_images` is safe to run repeatedly. It runs opportunistically when an upload is queued
and from `flask purge-job-images`, which is also how rows from before this existed are cleaned.
"""
import json
import os
from datetime import datetime, timedelta

from backend.db import db
from backend.models import Job

IMAGE_JOB_TYPES = ("process_upload", "extract_chart")
EMPTY_PAYLOAD = "{}"
ABANDONED_HOURS = 24


def ttl_hours():
    try:
        return float(os.environ.get("JOB_IMAGE_TTL_HOURS", "1"))
    except ValueError:
        return 1.0


def empty_payload(job):
    """Drop the uploaded image from a job's input. No commit."""
    if job.type in IMAGE_JOB_TYPES and job.payload != EMPTY_PAYLOAD:
        job.payload = EMPTY_PAYLOAD


def strip_result_image(result_text):
    """Return result JSON without image_data_url, or None when there was nothing to strip."""
    if not result_text or "image_data_url" not in result_text:
        return None
    try:
        data = json.loads(result_text)
    except ValueError:
        return None
    if not isinstance(data, dict) or "image_data_url" not in data:
        return None
    data.pop("image_data_url")
    data.pop("image_mime", None)
    return json.dumps(data)


def purge_job_images(older_than_hours=None, dry_run=False, batch=100, limit=None):
    """Remove stored images from image jobs older than the TTL. Returns
    {"payloads": n, "results": n}, the rows changed (or that would change with dry_run)."""
    hours = ttl_hours() if older_than_hours is None else float(older_than_hours)
    now = datetime.utcnow()
    cutoff = now - timedelta(hours=hours)
    abandoned = now - timedelta(hours=max(hours, ABANDONED_HOURS))
    counts = {"payloads": 0, "results": 0}

    # Inputs: finished or failed jobs after the TTL; anything else only once it is abandoned.
    q = Job.query.filter(
        Job.type.in_(IMAGE_JOB_TYPES),
        Job.payload != EMPTY_PAYLOAD,
        db.or_(
            db.and_(Job.status.in_(("done", "failed")), Job.created_at < cutoff),
            Job.created_at < abandoned,
        ),
    )
    if limit:
        q = q.limit(limit)
    for job in q.all():
        counts["payloads"] += 1
        if not dry_run:
            job.payload = EMPTY_PAYLOAD
    if not dry_run:
        db.session.commit()

    # Results: the embedded copy of the image.
    q = Job.query.filter(
        Job.type.in_(IMAGE_JOB_TYPES),
        Job.created_at < cutoff,
        Job.result.like('%"image_data_url"%'),
    )
    if limit:
        q = q.limit(limit)
    pending = 0
    for job in q.all():
        stripped = strip_result_image(job.result)
        if stripped is None:
            continue
        counts["results"] += 1
        if not dry_run:
            job.result = stripped
            pending += 1
            if pending >= batch:
                db.session.commit()
                pending = 0
    if not dry_run:
        db.session.commit()
    return counts


def purge_quietly():
    """Opportunistic purge for request handlers: bounded, and never allowed to fail a request."""
    try:
        purge_job_images(limit=200)
    except Exception:
        db.session.rollback()
