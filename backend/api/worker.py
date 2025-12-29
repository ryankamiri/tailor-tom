"""Celery worker entry point for TailorTom."""

from api.celery_app import celery_app

# This module is used as the Celery app entry point
# Run with: celery -A api.worker worker --loglevel=info --concurrency=3

__all__ = ["celery_app"]

