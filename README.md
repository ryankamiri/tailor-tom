# TailorTom - ATS Resume Optimizer

TailorTom is a free and open-source full-stack web application that optimizes your resume for Applicant Tracking Systems (ATS). Start with LaTeX or upload a Word (.docx) resume—we convert it to LaTeX, then use DSPy and GPT to incorporate relevant keywords from job descriptions while keeping your resume within your target page count.

## About

I created TailorTom to help job seekers navigate the challenging ATS landscape. ATS systems can be difficult to crack, and getting your resume past them to reach human reviewers is often the hardest part of the job application process. This tool is designed to help optimize your resume for better ATS compatibility.

**Created by:** [Ryan Amiri](https://x.com/RyanAmiri__)  
**LinkedIn:** [ryanamiri](https://www.linkedin.com/in/ryanamiri/)  
**GitHub:** [ryankamiri/tailor-tom](https://github.com/ryankamiri/tailor-tom)

This is an open-source project built for fun to help others with their job applications.

## Features

- **DOCX to LaTeX**: Upload a Word (.docx) resume and convert it to LaTeX automatically (no LaTeX experience required)
- **ATS Keyword Optimization**: Automatically incorporates relevant keywords from job descriptions
- **Line-Count Preservation**: Optimizes bullets while maintaining exact line counts (no layout changes)
- **No Hallucination**: Only rephrases existing content—never invents new experiences
- **Visual Diff Comparison**: Side-by-side PDF comparison with highlighted changes
- **Word-Level Diff**: See exactly what changed with detailed text and LaTeX diffs
- **LaTeX Editor**: Edit your resume LaTeX directly in the browser with syntax highlighting; PDF preview on save and on load
- **PDF Export**: Download optimized resumes as PDFs
- **Job Queue Management**: Track multiple optimization jobs with status updates
- **Desktop Notifications**: Get notified when optimizations complete
- **Dark Mode**: Beautiful dark theme support

## Architecture

### Full-Stack Application

- **Frontend**: Next.js 16 with React 19, TypeScript, Tailwind CSS, and shadcn/ui
- **Backend**: FastAPI with Python 3.10+, DSPy, and PyMuPDF
- **Deployment**: 
  - Frontend: Vercel 
  - Backend: Render

### Optimization Pipeline

TailorTom uses a **line-count preserving optimizer** that validates changes by compiling and checking actual line counts:

```
[Resume LaTeX + Job Description]
              │
              ▼
    ┌─────────────────────┐
    │   pdflatex compile  │  ◄── Get baseline PDF
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Extract Bullet     │  ◄── Line count for each bullet
    │  Constraints        │      (e.g., "2 lines", "1 line")
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Optimize Bullets   │  ◄── GPT-5-mini + ChainOfThought
    │  (DSPy Module)      │      "MUST stay N lines"
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Apply All          │  ◄── Replace LaTeX snippets
    │  Replacements       │
    └──────────┬──────────┘
               │
               ▼
    ┌─────────────────────┐
    │  Compile & Check    │  ◄── pdflatex → extract new line counts
    │  Line Counts        │
    └──────────┬──────────┘
               │
          ┌────┴────┐
          │ Same?   │
          └────┬────┘
         Yes   │   No
          │    │    │
          ▼    │    ▼
      [Accept] │  [Revert + Feedback]
               │    "went from 2 to 3 lines"
               └────┘  (retry with feedback)
```

**Key Features:**
- **Line-count validation**: Checks actual rendered line counts, not word/char estimates
- **Compile-and-verify**: Applies changes, compiles PDF, then validates
- **Selective revert**: Only reverts bullets that changed line count
- **Clear feedback**: "TOO LONG: went from 2 to 3 lines. Use shorter words."
- **Section filtering**: Education and Skills sections are never modified
- **Structured output**: Uses DSPy ChainOfThought with Pydantic-typed signatures

## Prerequisites

### Local Development

- **Python 3.10+**
- **Node.js 18+** and npm
- **pdflatex** (LaTeX distribution)
- **OpenAI API key**

### Installing LaTeX (macOS)

```bash
# Full MacTeX (5GB, everything included)
brew install --cask mactex

# OR BasicTeX (100MB, minimal)
brew install --cask basictex
```

## Installation

### Backend Setup

1. Navigate to the backend directory:
```bash
cd backend
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
# Create .env file in backend/ directory
OPENAI_API_KEY=your_api_key_here
MODEL_NAME=openai/gpt-5-mini
OPTIMIZER_MAX_WORKERS=2
COMPILE_TIMEOUT=30
```

5. Run the backend server:
```bash
uvicorn api.main:app --reload
```

The API will be available at `http://localhost:8000`

### Frontend Setup

1. Navigate to the frontend directory:
```bash
cd frontend
```

2. Install dependencies:
```bash
npm install
```

3. Set up environment variables:
```bash
# Create .env.local file
NEXT_PUBLIC_API_URL=http://localhost:8000
```

4. Run the development server:
```bash
npm run dev
```

The frontend will be available at `http://localhost:3000`

## Configuration

### Backend Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | Your OpenAI API key |
| `MODEL_NAME` | `openai/gpt-5-mini` | DSPy model identifier |
| `REDIS_URL` | (required) | Redis URL for Celery broker and job storage (e.g., `redis://localhost:6379/0`) |
| `COMPILE_TIMEOUT` | `30` | pdflatex timeout in seconds |
| `REDIS_TTL_DAYS` | `7` | Number of days to keep completed jobs in Redis |
| `CELERY_TASK_TIME_LIMIT` | `600` | Maximum time in seconds for a Celery task (10 minutes) |
| `CELERY_WORKER_CONCURRENCY` | `3` | Number of concurrent Celery worker processes |
| `MAX_TOKENS` | `None` | Max tokens for LLM (None = model default) |
| `TEMPERATURE` | `None` | LLM temperature (None = model default) |

### Frontend Environment Variables

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Backend API URL (default: `http://localhost:8000`) |

### Optimization Settings (Frontend UI)

These settings are configured in the Settings page and sent with each job request:

- **Target Pages**: 1-3 pages (default: 1)
- **Max Iterations**: 2-5 iterations (default: 3)
- **Max Bullet Lines**: 1-3 lines per bullet (default: 2)

## Deployment

### Frontend Deployment (Vercel)

1. Push your code to GitHub
2. Import your repository in [Vercel](https://vercel.com)
3. Set the root directory to `frontend`
4. Add environment variable:
   - `NEXT_PUBLIC_API_URL`: Your Render backend URL
5. Deploy!

### Backend Deployment (Render)

#### Architecture Overview

TailorTom uses a **Celery + Redis** architecture for job processing:

```
FastAPI API (Render) → Redis Queue → Celery Workers (Render)
```

- **API Service**: Handles HTTP requests, validates LaTeX, enqueues jobs
- **Redis**: Job queue and persistent job storage
- **Worker Service**: Processes optimization jobs independently

#### Step 1: Set Up Redis

**Option A: Upstash (Recommended for start - Free tier available)**
1. Create account at [Upstash](https://upstash.com)
2. Create a new Redis database
3. Copy the Redis URL (format: `redis://default:password@host:port`)

**Option B: Render Redis (Production)**
1. In Render dashboard, create a new **Redis** service
2. Copy the **Internal Redis URL** from the service dashboard
3. Cost: $15/month (256MB) or $25/month (1GB)

#### Step 2: Deploy API Service

1. Push your code to GitHub
2. Create a new **Web Service** in [Render](https://render.com)
3. Connect your GitHub repository
4. Configure the service:
   - **Name**: `tailortom-api` (or your preferred name)
   - **Environment**: `Docker`
   - **Dockerfile Path**: `backend/Dockerfile`
   - **Docker Context**: Root of repository
   - **Start Command**: (leave empty, Dockerfile handles this)
5. Add environment variables:
   ```
   OPENAI_API_KEY=your_api_key_here
   MODEL_NAME=openai/gpt-5-mini
   REDIS_URL=redis://your_redis_url_here
   COMPILE_TIMEOUT=30
   CELERY_WORKER_CONCURRENCY=3
   REDIS_TTL_DAYS=7
   ```
6. Deploy!

#### Step 3: Deploy Worker Service

1. Create a **second Web Service** in Render (same repository)
2. Configure the service:
   - **Name**: `tailortom-worker` (or your preferred name)
   - **Environment**: `Docker`
   - **Dockerfile Path**: `backend/Dockerfile.worker`
   - **Docker Context**: Root of repository
   - **Start Command**: leave default (image CMD consumes both `hosted` and `docx` queues)
3. Add **the same environment variables** as the API service:
   ```
   OPENAI_API_KEY=your_api_key_here
   MODEL_NAME=openai/gpt-5-mini
   REDIS_URL=redis://your_redis_url_here
   COMPILE_TIMEOUT=30
   CELERY_WORKER_CONCURRENCY=3
   CELERY_QUEUE_NAME=hosted
   REDIS_TTL_DAYS=7
   ```
4. **Plan**: Starter ($7/month) - can handle 3-5 concurrent jobs
5. Deploy!

### Render Free Tier Considerations

**Recommended Setup for Free Tier:**
- **API Service**: Render Starter ($7/month) - handles requests
- **Worker Service**: Render Starter ($7/month) - processes jobs
- **Redis**: Upstash Free tier ($0/month) - 10K commands/day, 256MB
- **Total Cost**: $14/month

**Worker Concurrency:**
- **Starter Plan**: Set `CELERY_WORKER_CONCURRENCY=3` (512MB RAM, 0.5 CPU)
- **Standard Plan**: Can increase to `CELERY_WORKER_CONCURRENCY=5` (4GB RAM, 1 CPU)

**Why Separate Services?**
- API stays responsive (doesn't block on job processing)
- Workers can scale independently based on queue depth
- Jobs persist in Redis (survive service restarts)
- Production-ready architecture pattern

**Scaling:**
- **Low traffic** (< 100 users/day): 1 worker service with 3 concurrency
- **Medium traffic** (100-500 users/day): 1 worker service with 3-5 concurrency
- **High traffic** (500+ users/day): Multiple worker services or upgrade to Standard plan

## Project Structure

```
TailorTom/
├── backend/
│   ├── api/                    # FastAPI application
│   │   ├── main.py            # FastAPI app and middleware
│   │   ├── models.py          # Pydantic request/response models
│   │   ├── storage.py         # Redis-based job storage
│   │   ├── celery_app.py      # Celery application configuration
│   │   ├── tasks.py           # Celery task definitions
│   │   ├── worker.py          # Celery worker entry point
│   │   └── routes/            # API route handlers
│   │       ├── optimize.py   # Job creation and enqueueing
│   │       ├── jobs.py       # Job status and management
│   │       ├── diff.py       # Diff computation endpoints
│   │       ├── compile.py    # LaTeX compilation endpoints
│   │       ├── convert.py    # DOCX to LaTeX conversion
│   │       ├── settings.py  # Resume storage
│   │       └── admin.py      # Admin dashboard
│   ├── tailor_tom/            # Core business logic
│   │   ├── config.py         # Configuration management
│   │   ├── optimizer.py      # DSPy modules and pipeline
│   │   ├── latex_compiler.py # LaTeX compilation
│   │   ├── layout_analyzer.py # PDF layout analysis
│   │   ├── docx_converter.py # DOCX extraction and JSON classification
│   │   ├── resume_renderer.py # Deterministic LaTeX renderer (Option D)
│   │   └── diff_utils.py     # Diff computation and PDF highlighting
│   ├── Dockerfile            # Docker configuration for Render
│   └── requirements.txt      # Python dependencies
├── frontend/                 # Next.js application
│   ├── app/                  # Next.js app router pages
│   ├── components/           # React components
│       │   ├── jobs/        # Job-related components
│       │   ├── diff/        # Diff visualization components
│       │   ├── editor/      # LaTeX editor component
│       │   ├── layout/      # Layout components (navbar, theme)
│       │   ├── settings/    # Settings form component
│       │   └── ui/          # shadcn/ui components
│       └── lib/             # Utility functions and API client
├── notebooks/               # Jupyter notebooks (experimentation)
└── README.md
```

## How It Works

1. **Set up resume (Settings)**: Paste LaTeX or upload a Word (.docx) resume. We convert DOCX to LaTeX and show a live PDF preview. Save your template and preferences.
2. **User submits a job**: Provides job description; resume and optimization settings come from Settings
3. **API validates**: FastAPI validates LaTeX syntax and job description length
4. **Job enqueued**: Job is stored in Redis and enqueued to Celery task queue
5. **Worker processes**: Celery worker picks up job and runs the line-count preserving optimizer:
   - **Compile original**: PDF is compiled to extract bullet line counts
   - **Extract constraints**: Each bullet gets a `BulletConstraint` with its line count (e.g., "2 lines")
   - **Filter sections**: Education and Skills bullets are excluded (never modified)
   - **LLM optimization**: DSPy ChainOfThought generates replacements with keywords integrated
   - **Apply all replacements**: All LLM outputs are applied to the LaTeX
   - **Compile and verify**: PDF is compiled and line counts are checked for each bullet
   - **Selective revert**: Bullets that changed line count are reverted with feedback ("went from 2 to 3 lines")
   - **ICL retry loop**: Failed bullets get specific feedback and retry up to max_iterations
   - **Final compile**: Optimized LaTeX compiled with all accepted changes
6. **Status updates**: Worker updates job status in Redis throughout processing
7. **Diff Generation**: Word-level diff is computed and PDFs are annotated with highlights (on-demand)
8. **Results**: User can view diffs, edit LaTeX, and download optimized PDF

## API Endpoints

### Optimization
- `POST /api/optimize` - Create a new optimization job
- `GET /api/jobs/{job_id}` - Get job status
- `GET /api/jobs/{job_id}/latex` - Get optimized LaTeX
- `POST /api/jobs/{job_id}/cancel` - Cancel a pending job
- `DELETE /api/jobs/{job_id}` - Delete a completed job

### Compilation
- `POST /api/compile/validate` - Validate LaTeX syntax
- `POST /api/compile` - Compile LaTeX to PDF

### Conversion
- `POST /api/convert/docx` - Convert a .docx resume to LaTeX (multipart: file, target_pages default 1)

### Diff
- `POST /api/diff` - Compute text diff between two LaTeX strings
- `POST /api/diff-pdfs` - Generate annotated PDFs with highlights

## Contributing

Contributions are welcome! This is an open-source project built to help job seekers. Please feel free to submit issues and pull requests.

## License

MIT License - see LICENSE file for details.
