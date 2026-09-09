# Job Agent - personal AI job-search and application assistant

Discovers relevant jobs from public job APIs, scores them against your profile with an LLM,
generates tailored application material (resume + grounded answers), fills application forms
with Playwright and tracks every application - while **you stay in control of the final submit**.

```
Scheduled search -> collect -> normalize -> dedupe -> rule filter -> cheap AI filter
   -> AI match scoring (0-100) -> dashboard -> you approve -> tailored resume + answers
   -> browser fills the form -> you review -> YOU submit -> tracker
```

Designed for near-zero monthly cost: SQLite, free-tier Gemini + OpenRouter free models,
aggressive AI caching, and public job APIs only (no scraping behind logins or CAPTCHAs).

---

## 1. Quick start (local)

Prerequisites: Python 3.12+, Node 20+, Git. Docker is optional.

```powershell
# Windows PowerShell - from the project root
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium

cd frontend
npm install
npm run build          # builds frontend/dist, served by the backend
cd ..

copy .env.example .env  # then add your API keys (see section 3)

cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

```bash
# macOS / Linux
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
(cd frontend && npm install && npm run build)
cp .env.example .env
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000
```

Open **http://127.0.0.1:8000** - the dashboard. API docs live at `/docs`.

On first start the database is created in `data/job_agent.db`, your profile is seeded
(edit it on the **Profile** page) and 7 sample jobs are inserted so the UI is not empty.

### Development mode (hot reload)

```powershell
.\scripts\dev.ps1          # Windows: backend --reload on :8000 + Vite dev server on :5173
./scripts/dev.sh           # macOS / Linux
```

The Vite dev server proxies `/api` to the backend.

### Docker

```bash
cp .env.example .env       # fill in keys
docker compose up --build  # http://localhost:8000
```

The container runs the browser headless; use the local setup when you want to watch
the browser fill a form and submit it yourself.

---

## 2. Everyday workflow

1. **Dashboard -> "Search jobs now"** runs the discovery pipeline in the background
   (or let the scheduler do it every morning - Settings -> Scheduler).
2. **Jobs** shows scored jobs with matched skills, missing requirements and an
   APPLY / REVIEW / LOW PRIORITY / REJECT recommendation. Filter by score, role,
   location, remote, company, source or application status.
3. Click **Prepare Application** on a job. On the application page click
   **Prepare application material**: a resume tailored *only* from your profile facts
   (PDF download) and answers to common questions. Anything the profile cannot support is
   flagged **needs review** - edit it in place.
4. Paste the application URL and click **Fill Application**. A Chromium window opens, the
   form is inspected, safe fields are filled from your profile, the resume is uploaded and
   text questions are answered. The agent **never clicks submit**.
5. Review the form in the browser, submit it yourself, then click
   **"I submitted it manually - mark as APPLIED"**.
6. Track status (INTERVIEW, OFFER, REJECTED...), notes, follow-up dates on **Applications**.

Try the browser agent safely on the bundled fake site:
`http://127.0.0.1:8000/fake-job-site/` (nothing is sent anywhere).

---

## 3. Configuration (`.env`)

Copy `.env.example` to `.env`. Nothing secret is ever committed or shown in the UI.

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Gemini (default `gemini-2.5-flash`). Used for job analysis, resume tailoring, answers. |
| `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` | OpenRouter (default a free Llama model). Used for cheap classification + fallback. Run `python scripts/list_openrouter_free_models.py` to pick a free model. |
| `AI_ROUTE_*` | Provider chain per task, e.g. `AI_ROUTE_JOB_ANALYSIS=gemini,openrouter`. Entries may pin a model: `openrouter:google/gemma-3-27b-it:free`. |
| `*_PROMPT_VERSION` | Bump to invalidate cached results for one task after editing a prompt in `/prompts`. |
| `DATABASE_URL` | SQLite by default; `postgresql+psycopg://...` also works (`pip install -r requirements-postgres.txt`). |
| `JOB_SOURCES_ENABLED` | Comma list of sources (also editable in Settings). |
| `ADZUNA_APP_ID/KEY` | Optional free Adzuna key - best source for India / Bangalore onsite roles. |
| `SCHEDULER_ENABLED`, `SCHEDULE_CRON`, `SCHEDULE_TIMEZONE` | Defaults for the in-process scheduler (override in Settings). |
| `NOTIFICATION_PROVIDERS` + `SMTP_*` / `TELEGRAM_*` | `console`, `email`, `telegram` - daily report channels. |
| `BROWSER_HEADLESS`, `BROWSER_KEEP_OPEN` | Keep `false`/`true` locally so you can review and submit in the opened window. |

At least one of `GEMINI_API_KEY` / `OPENROUTER_API_KEY` is required for AI features.
Everything else (discovery, rule filtering, tracker, dashboard) works without keys.

### Job sources

| Source | Type | Needs |
|--------|------|-------|
| remotive, arbeitnow, remoteok, jobicy | public JSON APIs (remote jobs) | nothing |
| adzuna | official search API, India coverage | free developer key |
| greenhouse, lever, ashby | company career pages via public job-board APIs | company slugs in Settings -> Company career pages |
| linkedin, naukri, indeed | **not automated** (login walls, CAPTCHAs, terms of service) | connector interface only - see `backend/app/jobs/sources/unsupported.py` |

Add your own: subclass `JobSource` in `backend/app/jobs/sources/`, return `NormalizedJob`s,
register it in `registry.py`.

---

## 4. How the AI is kept cheap and honest

* **Rules first.** `backend/app/jobs/filters.py` rejects internships, senior/director roles,
  unrelated functions, stale postings, onsite roles outside your locations, remote roles
  restricted to other countries/regions (e.g. "USA only"), and roles requiring far more
  experience - before any LLM call. Rules are editable in Settings; after changing them click
  **Re-apply rules to unanalyzed jobs** (or `POST /api/jobs/refilter`). On a real run this cut
  129 discovered jobs down to 16 candidates for AI analysis.
* **Cheap model second.** Ambiguous titles go through a tiny classification prompt on the
  cheap route (OpenRouter free model by default).
* **Strong model only when necessary**, capped per run (`AI_MAX_ANALYSES_PER_RUN`).
* **Caching.** Every structured result is stored in `ai_results` keyed by
  `(task, job_hash, profile_version, prompt_version)`. Re-running never re-analyzes an
  unchanged job; editing your profile bumps `profile_version` so results refresh.
* **Rate limits.** Per-provider request spacing, bounded exponential backoff, provider
  fallback (`Gemini -> OpenRouter`), never infinite retries.
* **Schema validation.** Every AI response is parsed into a Pydantic model
  (`backend/app/schemas/ai.py`). The recommendation band is derived from the score in code,
  not by the model.
* **No fabrication.** Tailored resumes pass a grounding check (`ground_resume`) that removes
  skills, employers, projects, certifications and even numbers that do not exist in your
  master profile. Question answers that need facts the profile lacks are flagged `needs_review`.

Prompts live in `/prompts/*.txt` and are versioned - see `prompts/README.md`.

---

## 5. Project layout

```
backend/app/
  api/            FastAPI routers (jobs, applications, profile, dashboard, settings, runs)
  agents/         job_analyzer, resume_tailor, question_answerer, application_preparer
  ai/             provider abstraction (gemini, openrouter, fake), router, cache, prompts
  browser/        Playwright agent + deterministic field mapper (never submits)
  jobs/           sources/, normalize, dedupe, filters, pipeline
  models/         SQLAlchemy models (profile, job, application, ai cache, runs, settings)
  notifications/  console / email / telegram + daily report
  scheduler/      APScheduler wrapper (cron editable at runtime)
  services/       profile, jobs, applications, dashboard, settings, resume PDF
  main.py         app factory; container.py wires components
backend/tests/    unit + integration + browser tests
frontend/         React + TypeScript dashboard (Vite)
prompts/          versioned prompt files
fake-job-site/    local application form for safe browser testing
scripts/          run_search.py (cron/CI), dev helpers, OpenRouter model list
```

---

## 6. API

```
GET    /api/dashboard
GET    /api/jobs?min_score=&q=&role=&location=&remote=&company=&source=&recommendation=&application_status=&sort=&page=
GET    /api/jobs/{id}            PATCH /api/jobs/{id} {user_action}
POST   /api/jobs/search          {sources?, analyze, notify}  -> background run
POST   /api/jobs/refilter        re-apply rule filters to not-yet-analyzed jobs
POST   /api/jobs/{id}/analyze    POST /api/jobs/{id}/tailor-resume
GET    /api/applications         POST /api/applications {job_id}
GET    /api/applications/{id}    PATCH /api/applications/{id}    DELETE /api/applications/{id}
POST   /api/applications/{id}/prepare            {questions?, regenerate_resume?}
POST   /api/applications/{id}/answer-questions   {questions}
POST   /api/applications/{id}/fill               {url?, headless?}   (never submits)
POST   /api/applications/{id}/close-browser
GET    /api/applications/{id}/resume.pdf
GET    /api/profile              PATCH /api/profile
GET    /api/settings             PATCH /api/settings      GET /api/settings/env
POST   /api/settings/ai/test     POST /api/settings/notifications/test
GET    /api/search-runs          GET /api/failures
```

---

## 7. Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

* Unit: normalization, dedupe, rule filters, scoring bands, AI JSON validation, status
  transitions, field mapping, resume grounding.
* Integration: full pipeline with a fake source + fake AI provider, API endpoints, notifier,
  scheduler.
* Browser: fills `fake-job-site/index.html` headless and asserts the form was **not** submitted
  (auto-skipped if Chromium is not installed).
* Real provider round-trips run only when keys are present:
  `GEMINI_API_KEY=... pytest -m integration tests/test_providers_integration.py`.

---

## 8. Deployment options

| Piece | Free / cheap option |
|-------|---------------------|
| Frontend | `npm run build` -> upload `frontend/dist` to **Cloudflare Pages** (set the API origin via a Pages proxy / `_redirects`, or keep serving it from the backend). |
| Backend | Any small always-on host: Fly.io / Render free tier / a tiny VPS with `docker compose up -d`. The backend is a normal ASGI app; it is not a Cloudflare Worker (Playwright + SQLAlchemy need a Python runtime). |
| Database | SQLite volume (default). Move to Postgres (Supabase / Neon free tier) by changing `DATABASE_URL` and installing `requirements-postgres.txt` - see section 9. Cloudflare D1 would need a driver; the code only depends on SQLAlchemy. |
| Scheduler | In-process APScheduler when the backend runs 24/7, **or** the included GitHub Actions workflow (`.github/workflows/daily-search.yml`) running `scripts/run_search.py` against a hosted Postgres, **or** any cron calling `python scripts/run_search.py`. |
| Browser agent | Run locally (headed) so you can review and submit. Headless works in Docker for testing only. |

Everything works fully locally with no cloud configured.

---

## 9. Hosted database (Supabase) + scheduled runs with the computer off

1. In Supabase open **Connect** and copy the **Session pooler** string
   (`postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:5432/postgres`).
   Use the pooler, not the "direct" `db.<ref>.supabase.co` host: the direct host may only be
   reachable over IPv6, which GitHub Actions runners do not have. Replace `[YOUR-PASSWORD]`
   with the database password from **Settings -> Database** (the API keys are not the password).
2. Check the connection and create the tables:
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements-postgres.txt
   $env:DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
   .\.venv\Scripts\python.exe scripts\check_db.py
   ```
3. Optional - copy what you already have locally (profile, jobs, applications, AI cache):
   ```powershell
   .\.venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --target "postgresql://...same string..."
   ```
4. Put the same `DATABASE_URL` in `.env` so the dashboard on your laptop reads the shared database.
5. On GitHub -> repository **Settings -> Secrets and variables -> Actions** add secrets:
   `DATABASE_URL`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` (and optionally `ADZUNA_APP_ID`,
   `ADZUNA_APP_KEY`, `SMTP_*`, `TELEGRAM_*`). Add variables `NOTIFICATION_PROVIDERS`
   (e.g. `console,telegram`) and `DASHBOARD_URL` if you want them in the report.
6. Run the workflow once by hand (**Actions -> daily-job-search -> Run workflow**). From then on
   it runs at 08:00 IST daily; open the dashboard locally whenever you like and the scored jobs
   are already there.

Never paste the database password or API keys into chat, issues or commits; rotate any key that
was exposed.

---

## 10. Safety and limits

* Never bypasses CAPTCHAs, logins, rate limits or anti-bot systems; only public/documented APIs.
* Never submits an application; never fabricates resume content or answers.
* One application per job (DB constraint) and a check against applying twice to the same
  company/role.
* Consent checkboxes, EEO/diversity questions, passwords and visa yes/no selects are left for
  you - they are listed as "unmatched fields" after a fill.
* Job descriptions are stored as plain text (HTML stripped) and rendered as text only.
* API keys/tokens/cookies are never logged (redaction filter) and never committed (`.gitignore`).
* Failures are stored in `pipeline_failures` (Settings page shows run stats) - one bad job
  never stops a run.
