# STEM-Accessibility backend

Flask API that turns an uploaded flowchart image into an editable, accessible
representation (Mermaid JSON, alt text and long description).

Pipeline for an upload: **Google Cloud Vision OCR** (node labels) → **YOLO**
detection (`backend/pipeline/models/best.pt`, node shapes) → **vision LLM via
OpenRouter** (edges) → Mermaid JSON. Summaries and long descriptions are also
generated through OpenRouter.

The frontend lives in [`stem-accessibility/frontend`](https://github.com/stem-accessibility/frontend).

## Services it depends on

| Service | Used for | Config |
|---|---|---|
| Supabase | Auth (JWT verification) and Postgres | `SUPABASE_URL`, `SUPABASE_JWT_ISSUER`, `DATABASE_URL` |
| OpenRouter | Edge inference + summaries | `ACCESSFLOW_OPENROUTER_API_KEY`, `LLM_MODEL_EDGES`, `LLM_MODEL_SUMMARY` |
| Google Cloud Vision | OCR | Application Default Credentials (or `GOOGLE_CREDENTIALS`) |

The schema is managed with Alembic (Flask-Migrate); see
[Database migrations](#database-migrations).

## Run locally

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Settings are read from a `.env` file in the repository root (git-ignored, never
commit it). There are two ways to fill it in.

### Option A: contributor setup (no accounts needed)

Nothing here needs Supabase, Vercel or a cloud account. Create `.env` with:

```
AUTH_MODE=dev
AUTO_CREATE_TABLES=1
DATABASE_URL=sqlite:///db.sqlite
RUN_JOBS_INLINE=1
```

| Line | Why |
|---|---|
| `AUTH_MODE=dev` | Skips token verification; every request is one fixed local user (`dev@localhost`). Refused on Cloud Run. |
| `AUTO_CREATE_TABLES=1` | Creates the tables in the SQLite file on first start, so you can skip `make migrate`. |
| `DATABASE_URL=sqlite:///db.sqlite` | A local file; Flask puts it at `instance/db.sqlite`. |
| `RUN_JOBS_INLINE=1` | Runs each upload job inside the request, so no separate worker process is needed. |

Start it:

```bash
.venv/bin/python -m backend.app          # http://localhost:4999
```

`curl localhost:4999/repo` returns `[]` and `curl localhost:4999/whoami` returns
the dev user. Then run the [frontend](https://github.com/stem-accessibility/frontend)
with `VITE_AUTH_MODE=dev` and `VITE_API_URL=http://localhost:4999`.

This is enough to open, edit, save and publish diagrams, parse Mermaid, and use
the viewers. **Uploading a new image** also calls two paid services that you
supply yourself; add these lines to `.env`:

```
ACCESSFLOW_OPENROUTER_API_KEY=<your OpenRouter key>
LLM_MODEL_EDGES=google/gemini-3.1-flash-lite
LLM_MODEL_SUMMARY=google/gemini-3.1-flash-lite
```

and give the process Google Cloud Vision credentials (OCR). Use a project with
the Vision API enabled:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project <your-gcp-project>
```

### Option B: full setup (your own Supabase project)

Use this to test real sign-in or to match production. Copy the template and fill
it in (`cp .env.example .env`). Replace the Option A auth and database lines
with:

```
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_JWT_ISSUER=https://<project-ref>.supabase.co/auth/v1
DATABASE_URL=postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
ACCESSFLOW_OPENROUTER_API_KEY=<your OpenRouter key>
CORS_ORIGINS=http://localhost:5173
RUN_JOBS_INLINE=1
```

Then create the schema and start the server:

```bash
make migrate
.venv/bin/python -m backend.app          # http://localhost:4999
```

`/whoami` returns `401` without a token. The frontend then needs your project's
`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` (see its README).

To mimic production: `.venv/bin/gunicorn backend.wsgi:app --bind 127.0.0.1:4999 --workers 1 --threads 8`.

### Environment variables

| Variable | Purpose |
|---|---|
| `AUTH_MODE` | `dev` = no token verification, fixed local user (local development only) |
| `SUPABASE_URL` | `https://<ref>.supabase.co` (no trailing slash) |
| `SUPABASE_JWT_ISSUER` | `<SUPABASE_URL>/auth/v1` (the token's `iss`, **not** the JWKS URL) |
| `DATABASE_URL` | Supabase **Session pooler** string (the direct host is IPv6-only) |
| `ACCESSFLOW_OPENROUTER_API_KEY` | OpenRouter key (named to avoid clashing with a shell `OPENROUTER_API_KEY`) |
| `LLM_MODEL_EDGES`, `LLM_MODEL_SUMMARY` | OpenRouter model slugs, default `google/gemini-3.1-flash-lite` |
| `GOOGLE_CREDENTIALS` | Optional service-account JSON (one line) for hosts without ADC |
| `CORS_ORIGINS` | Comma-separated extra allowed origins, e.g. the Vercel URL |
| `CORS_ORIGIN_PATTERNS` | Comma-separated https origin patterns where `*` matches `a-z`, `0-9` and `-` only, e.g. `https://frontend-git-*-stem-accessibility.vercel.app` for Vercel preview branches. A pattern needs a literal domain after the last `*`; others are ignored. |
| `RUN_JOBS_INLINE` | `1` = process each job inside the request that created it (scale-to-zero / local dev) |
| `RUN_WORKER_IN_PROCESS` | `1` = run a polling worker thread in the web process (always-on hosts; leave `RUN_JOBS_INLINE` unset) |
| `TRUSTED_PROXY_HOPS` | How many proxies in front of the app append to `X-Forwarded-For` and are trusted when finding the caller's address for rate limits. Default `1` on Cloud Run, `0` elsewhere (the header is ignored). |
| `JOB_TIMEOUT_SECONDS` | Report a job stuck in `running` as failed after this long (default 900) |

`.env` and `*google-key.json` are git-ignored. Never commit credentials.

## Database migrations

Models in `backend/models.py` are the source of truth; Alembic generates and
applies the changes. History is in `migrations/versions/`.

```bash
make migrate                         # apply pending migrations to DATABASE_URL
make migration m="add foo column"    # autogenerate from model changes, then review the file
make migration-status                # current revision + drift check
```

- Run `make migrate` **before** deploying code that needs it (not at app
  startup: several Cloud Run instances can boot at once).
- `0002` is Supabase-only (the `profiles` table the frontend writes at sign-up,
  and RLS on every backend table) and is skipped on plain Postgres/SQLite.
  **Every new backend table needs RLS enabled in its migration**, because
  Supabase exposes the `public` schema over its REST API.
- A database that already has the schema but no `alembic_version` table:
  `flask db stamp 0002` (set `FLASK_APP=backend.app_factory:create_app`).
- Record user-visible changes in [`CHANGELOG.md`](CHANGELOG.md), including the
  migration IDs a release needs.

## Jobs

`POST /jobs/process-upload` and `/jobs/generate-summary` create a row in
`jobs`; the client polls `GET /jobs/<id>`.

- **Inline mode** (`RUN_JOBS_INLINE=1`): the job runs before the create call
  returns, so the first poll already sees `done`. This is what lets Cloud Run
  scale to zero, because CPU is only available while a request is in flight.
- **Worker mode**: leave inline off and run `python -m backend.jobs.worker`
  separately, or set `RUN_WORKER_IN_PROCESS=1` with a single gunicorn process.

## Deploy to Cloud Run (us-west1, scale to zero)

Run `make migrate` against the production `DATABASE_URL` first. One-time setup: enable Secret Manager, put `DATABASE_URL` and
`ACCESSFLOW_OPENROUTER_API_KEY` in it, and let the service account read them.

```bash
gcloud run deploy accessflow-backend \
  --project stem-accessibility --region us-west1 --source . \
  --service-account accessflow-backend@stem-accessibility.iam.gserviceaccount.com \
  --memory 4Gi --cpu 2 --timeout 600 --concurrency 4 \
  --min-instances 0 --max-instances 3 --allow-unauthenticated \
  --set-env-vars SUPABASE_URL=...,SUPABASE_JWT_ISSUER=...,CORS_ORIGINS=https://<frontend>.vercel.app \
  --set-secrets DATABASE_URL=DATABASE_URL:latest,ACCESSFLOW_OPENROUTER_API_KEY=ACCESSFLOW_OPENROUTER_API_KEY:latest
```

The container sets `RUN_JOBS_INLINE=1` by default. Cold starts load torch and
take tens of seconds. Then set `VITE_API_URL` to the service URL in the
frontend's Vercel project and redeploy it.

## Known gaps

- Anyone with an account can run uploads, which spend the deployment's Vision and
  OpenRouter credits. There is no per-user quota yet.
- No automated tests beyond `testing.py`.

## License

See [LICENSE](LICENSE). Copyright (c) 2025 University of Washington.

### Third-party licenses: Ultralytics YOLO is AGPL-3.0

Node-shape detection uses [Ultralytics YOLO](https://github.com/ultralytics/ultralytics)
(`ultralytics` in `requirements.txt`), which is licensed under the
**GNU Affero General Public License v3.0** (AGPL-3.0), and the bundled model
weights (`backend/pipeline/models/best.pt`) were trained with it. The AGPL's
terms, including its network-use provision (section 13), apply to that
component and to what you build and deploy with it. If you run a modified
version as a network service, read the [Ultralytics license](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)
and make sure you comply, or obtain a commercial license from Ultralytics.
Other dependencies carry their own licenses (see `requirements.txt`).
