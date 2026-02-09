"""FastAPI application for TailorTom backend."""

import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import optimize, jobs, diff, compile, settings, admin, convert
from tailor_tom.config import settings as app_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("Starting TailorTom API server...")
    logger.info("Celery queue for optimization tasks: %s (worker must use -Q %s)", app_settings.celery_queue_name, app_settings.celery_queue_name)
    yield
    # Shutdown
    logger.info("Shutting down TailorTom API server...")


app = FastAPI(
    title="TailorTom API",
    description="ATS Resume Optimization API",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Log HTTP exceptions before returning them."""
    # Don't log 404s for DELETE /api/jobs/{job_id} - it's idempotent and expected
    if (exc.status_code == 404 and 
        request.method == "DELETE" and 
        request.url.path.startswith("/api/jobs/")):
        # Expected behavior - job doesn't exist, deletion is idempotent
        pass
    else:
        logger.error(
            f"HTTPException: {exc.status_code} - {exc.detail} - "
            f"Path: {request.url.path} - Method: {request.method}"
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Log all unhandled exceptions."""
    logger.error(
        f"Unhandled exception: {type(exc).__name__}: {str(exc)} - "
        f"Path: {request.url.path} - Method: {request.method}"
    )
    logger.error(f"Traceback:\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error: {str(exc)}"},
    )

# CORS middleware
# Allow requests from frontend domains
# Note: FastAPI CORS doesn't support wildcards in allow_origins, so we use allow_origin_regex for Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://tailortom.org",
        "https://www.tailortom.org",
        "https://api.tailortom.org",  # Allow API to call itself if needed
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",  # Match any Vercel preview deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(optimize.router, prefix="/api", tags=["optimize"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])
app.include_router(diff.router, prefix="/api", tags=["diff"])
app.include_router(compile.router, prefix="/api", tags=["compile"])
app.include_router(settings.router, prefix="/api", tags=["settings"])
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(convert.router, prefix="/api", tags=["convert"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "TailorTom API", "version": "0.1.0"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

