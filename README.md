# TailorTom — ATS Resume Optimizer

TailorTom is a free, open-source full-stack app that optimizes your resume for Applicant Tracking Systems (ATS). Paste LaTeX or upload a Word (.docx) resume; we convert to LaTeX and use GPT to integrate keywords from job descriptions while preserving line counts and layout.

**Created by:** [Ryan Amiri](https://x.com/RyanAmiri__) · [LinkedIn](https://www.linkedin.com/in/ryanamiri/) · [GitHub](https://github.com/ryankamiri/tailor-tom)

---

## Architecture Overview

Deployment is **API + Worker + Redis + Postgres**, with optional **Caddy** for TLS on a VPS.

| Component | Role |
|-----------|------|
| **API** (FastAPI) | HTTP API; runs DB migrations on startup, then serves traffic. Enqueues jobs to Redis; job data lives in Postgres. |
| **Worker** (Celery) | Consumes optimization jobs from Redis; reads/writes jobs in Postgres. Starts only after API is healthy (migration gate). |
| **Redis** | Celery broker and result backend (queue only; not source of truth). |
| **Postgres** | Users, jobs, and job_global_stats. Schema managed by Alembic. |
| **Caddy** (optional) | Reverse proxy and TLS (e.g. for `api.tailortom.org`). |

```
[Client] → Caddy → API → Redis ← Worker
                ↓           ↓
            Postgres ←──────┘
```

- **Frontend** (Next.js) can be deployed separately (e.g. Vercel) and points `NEXT_PUBLIC_API_URL` at the API.

---

## Prerequisites

- **Docker & Docker Compose** (for VPS deployment)
- **Postgres 13+** (or use the Postgres 16 image in Compose)
- **OpenAI API key**
- For local dev: **Python 3.10+**, **Node.js 18+**, **LaTeX** (e.g. MacTeX/BasicTeX)

---

## Environment Setup

### VPS / Docker Compose (production-like)

1. At the **repo root** (same directory as `docker-compose.yml`), create `.env` from the VPS template:
   ```bash
   cp env.vps.example .env
   ```
2. Edit `.env` and set **required** values:
   - `OPENAI_API_KEY` — OpenAI API key
   - `REDIS_URL` — use `redis://redis:6379/0` (Compose service name)
   - `DATABASE_URL` — e.g. `postgresql://tailortom:YOUR_PASSWORD@postgres:5432/tailortom`
   - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` — must match `DATABASE_URL`
   - `JWT_SECRET` — long random string (e.g. `openssl rand -hex 32`)
   - `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FRONTEND_URL` — for Sign in with Google
3. Set `CELERY_QUEUE_NAME=hosted` (same for API and worker).

See **env.vps.example** for optional vars (Discord webhook, worker concurrency, JWT expiry, etc.). With `DISCORD_WEBHOOK_URL` set, terminal failures (optimization and DOCX conversion) send one alert per job/conversion ID, deduped via Redis.

**V3 mapping integrity:** The optimizer maps each bullet to a LaTeX item by similarity. You can set `OPTIMIZER_MAPPING_MIN_SIMILARITY` (default `0.74`, range 0–1). Bullets whose text does not match their LaTeX snippet above this threshold are dropped from optimization (not failed); the run continues with the rest. This prevents bullets from being applied to the wrong experience block. See **backend/.env.example** and **env.vps.example** for the optional variable.

### Local development (backend only)

1. In **backend/** create `.env` from the backend example:
   ```bash
   cd backend && cp .env.example .env
   ```
2. Set `DATABASE_URL`, `REDIS_URL`, `OPENAI_API_KEY`, and `JWT_SECRET` (see **backend/.env.example**).
3. Use `CELERY_QUEUE_NAME=local` and run Postgres + Redis (e.g. `docker compose up -d postgres redis` from repo root with the same `.env`).

---

## First Deploy (VPS)

1. **Prepare env**  
   Copy `env.vps.example` to `.env` at repo root and fill required variables (see Environment Setup).

2. **Start the stack**  
   From repo root:
   ```bash
   docker compose up -d --build
   ```
   - **API** and **worker** both use **backend/Dockerfile** (same image). The API runs migrations then uvicorn; the worker overrides the command to run Celery. If migrations fail, the API container exits and the worker will not start.
   - **Worker** depends on API **health**; it only starts consuming after the API healthcheck passes (migration has already completed).

3. **Confirm migration**  
   Optional: shell into the API container and check:
   ```bash
   docker compose exec api alembic current
   ```
   Should show the current revision (e.g. `f0a1b2c3d4e5 (head)`).

4. **Verification checklist** (see below).

---

## Migration Strategy and Commands

- **On every API startup**, the API container runs `alembic upgrade head` before starting uvicorn. No separate migration step is required for normal deploys.
- **DB-only migration run** (e.g. CI or a migration-only job): set only `DATABASE_URL` and run:
  ```bash
  alembic upgrade head
  ```
  Alembic does not require `OPENAI_API_KEY` or `REDIS_URL` for this.
- **Current revision:**
  ```bash
  alembic current
  ```
- **History:**
  ```bash
  alembic history
  ```

---

## Verification Checklist

After first deploy or after changes:

| Check | How |
|-------|-----|
| API healthy | `curl -s http://localhost:8000/health` → `{"status":"healthy"}` |
| DB at head | `docker compose exec api alembic current` → shows head revision |
| Queue / worker | Submit a test job from the frontend; worker logs show task consumption |
| Auth | Sign in with Google (if configured); JWT in response |

---

## Failure Recovery Playbook

| Symptom | What to do |
|--------|------------|
| API container exits on startup | Check API logs: `docker compose logs api`. Often migration failure (e.g. DB not reachable or migration error). Fix DB or fix migration, then restart. |
| Worker never starts | Worker waits for API **health**. Ensure API is up and `/health` returns 200. Check `docker compose ps` and API logs. |
| Migration fails (e.g. "relation already exists") | If DB was partially migrated, check `alembic current` and `alembic history`. Prefer fixing forward (new migration) over downgrading; see Rollback below. |
| 500 with `request_id` in response | Do not expose internal details to clients. Correlate with server logs: `grep request_id <log>` to find the traceback. |
| "Internal server error" only | Response is intentionally generic. Use `request_id` from the response body or `X-Request-ID` header to find the log line and traceback. |

---

## Ongoing Schema Changes (Adding Fields Safely)

1. **Edit the SQLAlchemy model** in `backend/api/db_models.py` (and any related code).
2. **Generate a migration:**
   ```bash
   cd backend
   alembic revision --autogenerate -m "add_user_preference_xyz"
   ```
3. **Review** the new file under `backend/alembic/versions/`. Remove or adjust any destructive or optional steps; avoid `DELETE`/`TRUNCATE` of user or job data without an explicit ops process.
4. **Apply:**  
   For local DB: `alembic upgrade head`.  
   For VPS: re-deploy the stack; the API startup migration gate will run the new migration.
5. **Deploy** the application code that uses the new schema.

**Policy:** Migrations must not perform destructive deletes of user/job data without a documented runbook. Additive columns and indexes are preferred.

---

## Rollback Guidance

- **When to downgrade:** Only when a migration was just applied and no app code has been deployed that relies on the new schema, and you need to revert the schema change. Use sparingly.
- **When to forward-fix:** If the app is already running with the new schema or data exists in the new columns, add a **new** migration to fix the schema (e.g. add a missing column, fix a constraint) rather than downgrading.
- **Downgrade one revision:**
  ```bash
  alembic downgrade -1
  ```
  Then fix the migration file or the model and re-apply.

---

## Local Development (Summary)

- **Backend:** `cd backend`, `cp .env.example .env`, set `DATABASE_URL`, `REDIS_URL`, `OPENAI_API_KEY`, `JWT_SECRET`. Run Postgres + Redis (e.g. via root `docker compose up -d postgres redis`). Apply migrations: `alembic upgrade head`. Start API: `uvicorn api.main:app --reload`. Start worker: `celery -A worker.app worker -Q local -l info`.
- **Frontend:** `cd frontend`, `npm install`, set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `.env.local`, `npm run dev`.
- **LaTeX (macOS):** `brew install --cask mactex` or `basictex`.

---

## Features

- DOCX → LaTeX conversion, ATS keyword optimization, line-count preservation, no hallucination
- Visual and word-level diff, LaTeX editor with live PDF preview, job queue, desktop notifications, dark mode

---

## Project Structure (High Level)

```
TailorTom/
├── backend/
│   ├── api/           # FastAPI app, routes, DB models
│   ├── worker/        # Celery app and tasks
│   ├── tailor_tom/    # Config, optimizer, LaTeX, DOCX, diff
│   ├── alembic/        # Migrations
│   ├── scripts/       # start-api.sh (migration gate + uvicorn)
│   └── Dockerfile
├── frontend/           # Next.js app
├── docker-compose.yml # API, worker, Postgres, Redis, Caddy
├── env.vps.example    # VPS .env template (repo root)
└── backend/.env.example  # Local dev .env template
```

---

## API Endpoints (Summary)

- **Jobs:** `POST /api/optimize`, `GET /api/jobs`, `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`, `DELETE /api/jobs/{id}`
- **Compile:** `POST /api/compile/validate`, `POST /api/compile`
- **Convert:** `POST /api/convert/docx`
- **Diff:** `POST /api/diff`, `POST /api/diff-pdfs`
- **Health:** `GET /health`

---

## Cleanup and maintenance

- **Dead-code checks:** Run `ruff check backend/` (or `pyflakes`) from repo root, excluding `backend/tailor_tom/optimizer/v1` if needed. Frontend: `npm run lint` in `frontend/` (ESLint; generated `.next` and `**/.next/**` are ignored).
- **Deprecated APIs:** No endpoints or response fields are deprecated in this pass. Any future deprecations will be listed in `docs/CLEANUP-INVENTORY.md` and remain available until an explicit removal ticket.
- **V1 no-touch policy:** Do not modify `backend/tailor_tom/optimizer/v1/`; it is frozen for compatibility.

---

## Contributing and License

Contributions are welcome. MIT License — see LICENSE.
