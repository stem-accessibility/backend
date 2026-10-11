import json
import os
import uuid
import base64
from datetime import datetime
from flask import Blueprint, request, jsonify, current_app, g
from werkzeug.utils import secure_filename
from backend.db import db
from backend.models import Job
from backend.auth import require_auth

jobs_bp = Blueprint("jobs", __name__)

# Jobs stuck in "running" longer than this are reported as failed (e.g. the
# instance was recycled mid-job on a scale-to-zero host).
JOB_TIMEOUT_SECONDS = int(os.environ.get("JOB_TIMEOUT_SECONDS", "900"))


def run_inline_if_enabled(job: Job):
    """With RUN_JOBS_INLINE=1, process the job now instead of leaving it for a worker."""
    if os.environ.get("RUN_JOBS_INLINE") != "1":
        return
    # Imported lazily: the worker module imports the app factory (circular otherwise).
    from backend.jobs.worker import run_job_inline

    run_job_inline(job)


def serialize_job(job: Job):
    return {
        "job_id": job.id,
        "type": job.type,
        "status": job.status,
        "result": json.loads(job.result) if job.result else None,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@jobs_bp.route("/jobs/test", methods=["POST"])
@require_auth
def enqueue_test_job():
    payload = request.get_json(silent=True) or {"message": "hello worker"}

    job = Job(
        type="test",
        payload=json.dumps(payload),
        status="queued",
        owner_id=g.user_id,
    )

    db.session.add(job)
    db.session.commit()
    run_inline_if_enabled(job)

    return jsonify({
        "job_id": job.id,
        "status": job.status,
    }), 201


@jobs_bp.route("/jobs/generate-summary", methods=["POST"])
@require_auth
def enqueue_summary_job():
    payload = request.get_json(silent=True) or {}

    diagram = payload.get("diagram")
    if not diagram:
        return jsonify({"error": "Missing required field: diagram"}), 400

    job = Job(
        type="generate_summary",
        payload=json.dumps(payload),
        status="queued",
        owner_id=g.user_id,
    )

    db.session.add(job)
    db.session.commit()
    run_inline_if_enabled(job)

    return jsonify({
        "job_id": job.id,
        "status": job.status,
    }), 201


from sqlalchemy.orm import load_only

@jobs_bp.route("/jobs/<int:job_id>", methods=["GET"])
@require_auth
def get_job(job_id):
    job = (
        Job.query
        .options(
            load_only(
                Job.id,
                Job.owner_id,
                Job.type,
                Job.status,
                Job.result,
                Job.error,
                Job.created_at,
                Job.started_at,
                Job.finished_at,
            )
        )
        .filter_by(id=job_id)
        .first_or_404()
    )

    # Jobs are private to the user who created them; don't reveal that others exist.
    if job.owner_id != g.user_id:
        return jsonify({"error": "Not found"}), 404

    if (
        job.status == "running"
        and job.started_at
        and (datetime.utcnow() - job.started_at).total_seconds() > JOB_TIMEOUT_SECONDS
    ):
        job.status = "failed"
        job.error = "Job timed out"
        job.finished_at = datetime.utcnow()
        db.session.commit()

    return jsonify({
        "job_id": job.id,
        "type": job.type,
        "status": job.status,
        "result": json.loads(job.result) if job.result else None,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }), 200

@jobs_bp.route("/jobs/process-upload", methods=["POST"])
@require_auth
def enqueue_upload_job():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"error": "Invalid file"}), 400

    img_bytes = file.read()
    if not img_bytes:
        return jsonify({"error": "Empty file"}), 400

    mime_type = file.mimetype or "image/png"

    payload = {
        "image_b64": base64.b64encode(img_bytes).decode("utf-8"),
        "original_filename": file.filename,
        "image_mime": mime_type,
    }

    job = Job(
        type="process_upload",
        payload=json.dumps(payload),
        status="queued",
        owner_id=g.user_id,
    )

    db.session.add(job)
    db.session.commit()
    run_inline_if_enabled(job)

    return jsonify({
        "job_id": job.id,
        "status": job.status,
    }), 201
    