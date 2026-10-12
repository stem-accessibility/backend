from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
import os
import click
from backend.routes.api import api_bp
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
        origins=["http://localhost:3000", "http://localhost:5173", *extra_origins],
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

    return app