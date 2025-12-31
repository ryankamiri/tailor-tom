"""Celery worker entry point for TailorTom."""

import logging
from api.celery_app import celery_app

# Configure logging for worker
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# This module is used as the Celery app entry point
# Run with: celery -A api.worker worker --loglevel=info --concurrency=3

__all__ = ["celery_app"]

