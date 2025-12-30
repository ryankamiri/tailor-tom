"""Celery application configuration for TailorTom."""

import logging
import os
from celery import Celery
from tailor_tom.config import settings

logger = logging.getLogger(__name__)

# Validate REDIS_URL before creating Celery app
redis_url = settings.redis_url
if not redis_url or not redis_url.strip():
    error_msg = (
        f"REDIS_URL is empty or invalid. "
        f"Environment variable REDIS_URL={os.getenv('REDIS_URL', 'NOT SET')}. "
        f"Settings redis_url={redis_url!r}"
    )
    logger.error(error_msg)
    raise ValueError(error_msg)

logger.info(f"Initializing Celery with broker: {redis_url[:20]}...")  # Log first 20 chars for security

# Create Celery app instance
celery_app = Celery(
    "tailortom",
    broker=redis_url,
    backend=redis_url,
    include=["api.tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Task serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Task execution
    task_time_limit=settings.celery_task_time_limit,  # Hard time limit (kills task)
    task_soft_time_limit=settings.celery_task_time_limit - 60,  # Soft limit (raises exception)
    task_acks_late=True,  # Acknowledge after task completion
    worker_prefetch_multiplier=1,  # Fair task distribution
    
    # Task retry configuration
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,  # Max 10 minutes
    task_retry_jitter=True,
    task_max_retries=3,
    
    # Result backend
    result_expires=3600,  # Results expire after 1 hour
    
    # Worker configuration
    worker_max_tasks_per_child=50,  # Restart worker after 50 tasks (memory management)
    worker_disable_rate_limits=False,
)

logger.info(f"Celery app configured with broker: {redis_url[:20]}...")

