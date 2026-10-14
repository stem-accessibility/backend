from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
import os
import re
import click
from backend.routes.api import api_bp
from backend.routes.charts import charts_bp
from backend.routes.jobs import jobs_bp
from backend.routes.guest import guest_bp
from backend.db import db, migrate
from backend.models import (
    Flowchart,
    LongDescription,
    Job,
    StudyAccount,
    StudySession,
    ArtifactSnapshot,
)


def cors_origin_patterns(value: str) -> list:
    """Turn a comma-separated list of origin patterns into compiled regexes.

    Each pattern is a full origin where `*` stands for one or more of `a-z`, `0-9` or `-`
    (a single hostname label part, never a dot or slash), e.g.
    `https://frontend-git-*-stem-accessibility.vercel.app`. Patterns must be https and must
    keep a literal domain after the last `*`; anything else is ignored so a typo cannot
    open the API to every site.
    """
    compiled = []
    for raw in value.split(","):
        p = raw.strip().rstrip("/")
        if not p.startswith("https://") or "*" not in p:
            continue
        tail = p.rsplit("*", 1)[1]
        if "." not in tail or "/" in p[len("https://"):]:
            continue
        regex = re.escape(p).replace(r"\*", "[a-z0-9-]+")
        compiled.append(re.compile(regex + r"\Z", re.IGNORECASE))
    return compiled


def create_app():
    load_dotenv()

    app = Flask(__name__)

    # Comma-separated list of extra allowed origins, e.g. the deployed frontend URL.
    extra_origins = [
        o.strip().rstrip("/")
        for o in os.environ.get("CORS_ORIGINS", "").split(",")
        if o.strip()
    ]

    CORS(
        app,
        origins=[
            "http://localhost:3000",
            "http://localhost:5173",
            *extra_origins,
            *cors_origin_patterns(os.environ.get("CORS_ORIGIN_PATTERNS", "")),
        ],
        allow_headers=["Content-Type", "Authorization", "X-Guest-Token"],
    )

    database_url = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    db.init_app(app)
    migrate.init_app(app, db)

    app.register_blueprint(jobs_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(charts_bp)
    app.register_blueprint(guest_bp)

    # Schema changes go through Alembic (`flask db upgrade`, see README). create_all()
    # is only a convenience for throwaway local SQLite databases.
    if os.environ.get("AUTO_CREATE_TABLES") == "1":
        with app.app_context():
            db.create_all()

    @app.cli.command("takedown")
    @click.argument("slug")
    def takedown(slug):
        """Unpublish and hide a public page by its slug (the part after /p/)."""
        from datetime import datetime

        r = Flowchart.query.filter_by(public_slug=slug).first()
        if not r:
            click.echo(f"No page with slug {slug}")
            return
        r.is_published = False
        r.visibility = "private"
        r.published_at = None
        r.deleted_at = datetime.utcnow()
        db.session.commit()
        click.echo(f"Took down {slug} (owner {r.owner_id})")

    @app.cli.command("migrate-images")
    @click.option("--dry-run", is_flag=True, help="Count what would move without changing anything.")
    def migrate_images_cmd(dry_run):
        """Move originals stored inline on flowchart and long_descriptions rows into stem_images."""
        from backend.image_store import migrate_legacy_images

        counts = migrate_legacy_images(dry_run=dry_run)
        verb = "would move" if dry_run else "moved"
        click.echo(f"{verb} {counts['moved']} images; {counts['skipped_unreadable']} could not be read and were left in place")

    @app.cli.command("purge-job-images")
    @click.option("--older-than-hours", type=float, default=None,
                  help="Age after which stored images are removed (default JOB_IMAGE_TTL_HOURS, 1).")
    @click.option("--dry-run", is_flag=True, help="Count what would change without changing it.")
    def purge_job_images_cmd(older_than_hours, dry_run):
        """Remove uploaded images still stored in the jobs table (inputs and embedded copies)."""
        from backend.jobs.retention import purge_job_images

        counts = purge_job_images(older_than_hours=older_than_hours, dry_run=dry_run, limit=None)
        verb = "would clear" if dry_run else "cleared"
        click.echo(f"{verb} {counts['payloads']} stored uploads and {counts['results']} embedded images")

    return app