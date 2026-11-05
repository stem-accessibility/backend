# PDF slide deck prototype

Upload a PDF, detect whole diagrams with Gemini, and crop them with Python. Each
crop goes through the existing OCR/graph reader. The frontend uses the existing
`autoDescribe` function and saves a description page with a permalink.

## Configuration

Install `requirements.txt`. Add these settings to the backend's git-ignored
`.env`, alongside the existing auth/database settings:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_DECK_MODEL=gemini-2.5-flash
LLM_MODEL_EDGES=gemini-2.5-flash
LLM_MODEL_SUMMARY=gemini-2.5-flash
RUN_JOBS_INLINE=0
RUN_WORKER_IN_PROCESS=0
```

Create the Gemini key in [AI Studio](https://aistudio.google.com/api-keys).
OpenRouter alone cannot run the deck detector. Google Cloud Vision OCR also
needs a project with billing and the Vision API enabled. For local development,
install the Google Cloud CLI and configure
[Application Default Credentials](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment):

```sh
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_CLOUD_PROJECT_ID
```

Use an account authorized for that project. Do not commit keys or credential
files, and never put them in frontend `VITE_*` settings. Both AI services have
quotas and may incur charges.

## Run

From the backend directory, activate your virtual environment and apply
migrations with `python -m flask --app backend.app:app db upgrade`. For a fresh
local SQLite demo only, `AUTO_CREATE_TABLES=1` can create the tables instead.
Do not mix that shortcut with migrations on an already populated database.

Start the API and worker in separate terminals, using the same environment:

```sh
# Terminal 1
python -m flask --app backend.app:app run --host 127.0.0.1 --port 4999 --no-reload

# Terminal 2
python -m backend.jobs.worker
```

Run **one worker**. Deck uploads always queue work; inline mode does not process
them. Hosted deployments need a worker that can keep running after an HTTP
response, rather than the existing request-only, scale-to-zero configuration.

Set the frontend's `VITE_API_URL` to this API and open `/decks/new`. Keep or
reopen the results page to finish saving descriptions. Detection and graph
extraction continue in the worker if the page closes.

## Behavior and limits

- PDF only, up to 20 pages / 20 MB. Export PPTX or Google Slides first.
- Gemini returns normalized `[ymin, xmin, ymax, xmax]` boxes for complete figures.
  Python validates, deduplicates and crops them. Where a single figure matches an
  embedded PDF image, its boundary helps avoid clipped labels.
- Retry keeps successful pages, diagrams and links. Original PDFs are removed
  after all pages have been detected; failed detection retains the PDF for retry.
- Uploads/results are owner-only. Finished diagrams are shared by link, including
  their cropped image, but are not added to Browse. Use non-sensitive test slides.
- The existing reader targets flowcharts. Charts and infographics may produce
  incorrect graphs or no nodes. Detection does not guarantee a usable description.
- No crop-selection UI or automatic cleanup of failed uploads yet.

## Tests

```sh
python -m unittest tests.test_decks -v
```

Tests use temporary databases and mocked AI/OCR. They cover validation, crops,
partial failure/retry, owner isolation and idempotent publication.

Reference: [Gemini spatial understanding example](https://github.com/google-gemini/cookbook/blob/main/quickstarts/Spatial_understanding.ipynb).
