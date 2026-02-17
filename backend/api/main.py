"""FastAPI application for TailorTom backend."""

import logging
import traceback
import uuid
from contextlib import asynccontextmanager
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import optimize, jobs, diff, compile, admin, convert, auth
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


def _get_request_id(request: Request) -> str:
    """Per-request ID: X-Request-ID if present and valid, else new UUID."""
    provided = request.headers.get("X-Request-ID", "").strip()
    if provided and len(provided) <= 128:
        return provided
    return str(uuid.uuid4())


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Set request_id on request.state and log it for correlation."""

    async def dispatch(self, request: Request, call_next):
        request_id = _get_request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Log HTTP exceptions; for 5xx return generic detail to avoid leaking internal errors."""
    request_id = getattr(request.state, "request_id", None) or _get_request_id(request)
    logger.error(
        "HTTPException: %s - %s - Path: %s - Method: %s - request_id=%s",
        exc.status_code, exc.detail, request.url.path, request.method, request_id,
    )
    detail = exc.detail
    if exc.status_code >= 500:
        detail = "Internal server error"
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail, "request_id": request_id},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Log unhandled exceptions; return generic message and request_id only (no leak)."""
    request_id = getattr(request.state, "request_id", None) or _get_request_id(request)
    logger.error(
        "Unhandled exception: %s - Path: %s - Method: %s - request_id=%s",
        type(exc).__name__, request.url.path, request.method, request_id,
    )
    logger.error("Traceback (request_id=%s):\n%s", request_id, traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={"X-Request-ID": request_id},
    )


# Request ID first so it's available to exception handlers
app.add_middleware(RequestIDMiddleware)

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
app.include_router(admin.router, prefix="/api", tags=["admin"])
app.include_router(convert.router, prefix="/api", tags=["convert"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "TailorTom API", "version": "0.1.0"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

