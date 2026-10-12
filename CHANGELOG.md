# Changelog

All notable changes to the backend. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each entry that needs a
database change lists the migration to run **before** deploying (`make migrate`).

## [Unreleased]

### Added
- Try it (no account): `GET/PUT/DELETE /guest/image` and `POST /guest/claim`. A browser token
  (`X-Guest-Token`, hashed into `guest:<hash>`) owns one public image; guests cannot use uploads or AI, always
  share publicly, and are limited in size (200 nodes, 400 edges, text lengths) and rate (per token and per IP,
  per process). `claim` moves the image into an account after sign-up. Responses include `guest: true`.
- `POST /p/<slug>/report` stores a report (table `reports`, **migration 0004 — run `make migrate` before
  deploying**); `flask takedown <slug>` unpublishes and hides a page.
- CORS allows the `X-Guest-Token` header.
- `tests/test_guest.py`.

## [0.2.0] — 2026-10-11

Deployed to Cloud Run (us-west1) from commit 47801cb. The database was already at migration 0003, so
`make migrate` was a no-op. Verified: `PUT /flowcharts/<id>/sharing` answers 401 without a token and
`GET /repo` answers 200.

### Added
- `PUT /flowcharts/<id>/sharing` with `{"sharing": "public" | "link" | "private", "image_public": bool}`:
  one setting that sets visibility and publication together (public = page + listed, link = page only,
  private = owner only). `POST /flowcharts` accepts `sharing`; responses include `sharing` and `image_public`.
- `image_public` column: the uploaded source image is served on public pages only when the owner opts in.
  **Migration 0003 — run `make migrate` before deploying.** It backfills `image_public = true` for rows that
  are already published, so existing public pages are unchanged.
- `tests/test_sharing.py` (`python -m unittest tests.test_sharing`).

### Changed
- `POST /publish/<id>` and `POST /research/<id>` (deprecated) now use the same helper. Setting
  visibility to public through `/research` also publishes, so a diagram can no longer be public but
  invisible. They keep working for the deployed frontend until the rename (issue #1).
- `GET /p/<slug>` reports `has_image` only when the source image is shared.

### Added
- `AUTH_MODE=dev`: run the API without a Supabase project (fixed local user, SQLite).
  Refused when `K_SERVICE` is set, so it cannot start on Cloud Run.

### Changed
- Documentation uses the project name "STEM-Accessibility". The `ACCESSFLOW_OPENROUTER_API_KEY`
  variable and the `accessflow-backend` Cloud Run service keep their names.

### Added
- `LICENSE` (University of Washington).

## [0.1.0] — 2026-10-11

Deployed to Cloud Run (us-west1) as revision `accessflow-backend-00003-hs9`.
Database: stamped at migration `0002`.

### Added
- Cloud Run deployment: `Dockerfile` (CPU-only torch), gunicorn entrypoint
  (`backend/wsgi.py`), `.dockerignore`.
- `RUN_JOBS_INLINE=1`: run each job inside the request that created it so the
  service can scale to zero; jobs stuck in `running` are reported as failed after
  `JOB_TIMEOUT_SECONDS`.
- `CORS_ORIGINS` env var for allowed browser origins.
- Alembic migrations via Flask-Migrate (`make migrate`). **Migrations:** `0001`
  baseline, `0002` Supabase `profiles` table + row-level security.
- `.env.example`, rewritten README.

### Changed
- LLM calls moved from `google-genai` to OpenRouter (`backend/llm.py`); models set by
  `LLM_MODEL_EDGES` / `LLM_MODEL_SUMMARY`. Model names sent by clients are ignored.
- OCR uses Application Default Credentials when `GOOGLE_CREDENTIALS` is unset.
- Tables are no longer created at startup; use migrations (`AUTO_CREATE_TABLES=1`
  restores the old behavior for throwaway SQLite databases).
- Hard-coded production CORS origins removed.

### Security
- `/jobs/*` require a login, and jobs are visible only to their creator
  (`jobs.owner_id`).
- Row-level security enabled on all backend tables (Supabase exposes `public`
  over its REST API). Service-account key files are git-ignored.

### Upgrading an existing database
Databases created before migrations existed (the schema already matches `0002`):
`flask db stamp 0002`. Fresh databases: `make migrate`.

## 0.0.0 — 2026-10-11
Snapshot of `stem-accessibility/flowchart-accessibility` at `main`, without
history, venv, local database or credentials.
