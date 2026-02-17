# Local development (one terminal)

Run the full app with **one terminal** instead of four.

## How it works

- **Dependencies in Docker:** Redis and Postgres run in containers. Start them once in the background.
- **App in one process:** API, Celery worker, and Next.js run together via `concurrently` (prefixed output: `[api]`, `[worker]`, `[web]`).

## One-time setup

1. **Python venv at repo root** (e.g. `.venv`). If you use `backend/.venv` instead, edit the `dev:api` and `dev:worker` scripts in root `package.json` to use `backend/.venv/bin/...`.
2. **Backend env:** Copy `backend/.env.example` to `backend/.env` and set:
   - `REDIS_URL=redis://127.0.0.1:6379/0`
   - `CELERY_QUEUE_NAME=local`
   - `DATABASE_URL=postgresql://tailortom:tailortom@127.0.0.1:5432/tailortom`
3. **Install root deps:** From repo root: `npm install` (installs `concurrently`).
4. **Frontend deps:** `cd frontend && npm install`.
5. **DB schema:** Migrations are required. After first `docker compose -f docker-compose.dev.yml up -d`, run `cd backend && alembic upgrade head`.

## Daily workflow

**Terminal 1 – start dependencies (once per machine boot / when you need them):**

```bash
docker compose -f docker-compose.dev.yml up -d
```

**Terminal 2 – run the app (API + worker + frontend):**

```bash
npm run dev
```

Then open the frontend (e.g. http://localhost:3000) and use the API (e.g. http://localhost:8000).

## Stop

- Stop the app: `Ctrl+C` in the terminal where `npm run dev` is running.
- Stop Redis + Postgres: `docker compose -f docker-compose.dev.yml down`.
