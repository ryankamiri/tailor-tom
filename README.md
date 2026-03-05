# TailorTom

Open-source ATS resume optimizer for LaTeX and DOCX resumes.

TailorTom helps users adapt resumes to a job description while preserving structure and readability. It provides:
- Resume optimization jobs (API + worker queue)
- LaTeX compile/preview + diff endpoints
- DOCX-to-LaTeX conversion
- Web UI for creating, tracking, and reviewing jobs

Created by: [Ryan Amiri](https://x.com/RyanAmiri__) · [LinkedIn](https://www.linkedin.com/in/ryanamiri/) · [GitHub](https://github.com/ryankamiri/tailor-tom)

---

## Tech Stack

- Backend API: FastAPI
- Worker: Celery
- Queue/Broker: Redis
- Database: Postgres
- Frontend: Next.js
- Resume rendering: LaTeX toolchain

---

## Run Locally

### Prerequisites

- Python 3.10+
- Node.js 18+
- Redis
- Postgres
- LaTeX installed (`xelatex` available)
- OpenAI API key

### 1) One-time setup

Backend env:

```bash
cd backend
cp .env.example .env
```

Set required values in `backend/.env`:
- `OPENAI_API_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `JWT_SECRET`

Install dependencies:

```bash
# repo root
python -m venv .venv
source .venv/bin/activate
cd backend && pip install -r requirements.txt
cd ../frontend && npm install
```

Run migrations:

```bash
cd backend
source ../.venv/bin/activate
alembic upgrade head
```

### 2) Start infra (Redis + Postgres)

From repo root:

```bash
docker compose up -d redis postgres
```

### 3) Start everything (recommended)

```bash
npm run dev
```

This runs API + worker + web concurrently from repo root.

Open: `http://localhost:3000`

### Manual fallback (if needed)

If you need to run services separately, use:
- `npm run dev:api`
- `npm run dev:worker`
- `npm run dev:web`

---

## Core Commands

Backend lint/check:

```bash
cd backend
ruff check .
```

Frontend lint:

```bash
cd frontend
npm run lint
```

---

## Contributing

Issues and PRs are welcome. Keep changes focused, test locally, and include migration notes for DB changes.

---

## License

MIT (see `LICENSE`).
