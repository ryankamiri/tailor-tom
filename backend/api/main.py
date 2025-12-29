"""FastAPI application for TailorTom backend."""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import optimize, jobs, diff, compile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    # Startup
    logger.info("Starting TailorTom API server...")
    yield
    # Shutdown
    logger.info("Shutting down TailorTom API server...")


app = FastAPI(
    title="TailorTom API",
    description="ATS Resume Optimization API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.vercel.app",
    ],  # Will be configured in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(optimize.router, prefix="/api", tags=["optimize"])
app.include_router(jobs.router, prefix="/api", tags=["jobs"])
app.include_router(diff.router, prefix="/api", tags=["diff"])
app.include_router(compile.router, prefix="/api", tags=["compile"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "TailorTom API", "version": "0.1.0"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}

