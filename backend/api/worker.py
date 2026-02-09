"""Celery worker entry point for TailorTom."""

import logging
from api.celery_app import celery_app

# Configure logging for worker - only log errors
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# This module is used as the Celery app entry point
#
# Production (Render): use Dockerfile.worker; set CELERY_QUEUE_NAME=hosted, CELERY_WORKER_CONCURRENCY=3.
# Local: watchfiles --filter python 'celery -A api.worker worker --loglevel=info --concurrency=1 -Q local --pool=solo'
# DOCX conversions use priority=0 and optimization uses priority=5 so DOCX runs first when both are queued.

__all__ = ["celery_app"]

