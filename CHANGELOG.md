# Changelog

All notable changes to the backend. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each entry that needs a
database change lists the migration to run **before** deploying (`make migrate`).

## [Unreleased]

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
