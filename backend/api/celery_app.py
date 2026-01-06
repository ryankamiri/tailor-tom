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

# Configure SSL options for rediss:// (TLS) connections
# Upstash Redis requires SSL but doesn't need certificate verification
# Add SSL parameters directly to the URL as query parameters (most reliable method)
is_tls = redis_url.startswith("rediss://")
broker_url = redis_url
backend_url = redis_url

if is_tls:
    # Add ssl_cert_reqs parameter to URL for both broker and backend
    # Use CERT_NONE for Upstash (no certificate verification needed)
    separator = "&" if "?" in redis_url else "?"
    broker_url = f"{redis_url}{separator}ssl_cert_reqs=CERT_NONE"
    backend_url = f"{redis_url}{separator}ssl_cert_reqs=CERT_NONE"
    logger.info("Added SSL certificate requirements to Redis URL for TLS connection")

# Create Celery app instance
celery_app = Celery(
    "tailortom",
    broker=broker_url,
    backend=backend_url,
    include=["api.tasks"],
    broker_connection_retry_on_startup=True,
)

# Get queue name from settings (default: 'default' for backward compatibility)
# Set CELERY_QUEUE_NAME=local for local backend/worker
# Set CELERY_QUEUE_NAME=hosted for hosted backend/worker
queue_name = settings.celery_queue_name

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
    
    # Broker transport options - optimize Redis connection usage
    # Reduce connection overhead and polling frequency
    broker_transport_options={
        'visibility_timeout': 3600,  # 1 hour - how long task is invisible after being received
        'fanout_prefix': True,  # Enable fanout for better performance
        'fanout_patterns': True,  # Enable pattern-based fanout
        'max_connections': 10,  # Limit connection pool size
        'retry_policy': {
            'timeout': 5.0,  # Connection timeout
        },
        # Reduce polling frequency by increasing socket timeout
        # This makes workers wait longer before checking for new tasks
        'socket_timeout': 30.0,  # Socket timeout (increases time between polls)
        'socket_connect_timeout': 5.0,
        'socket_keepalive': True,
        'socket_keepalive_options': {},
        # Use connection pooling more efficiently
        'health_check_interval': 30,  # Check connection health every 30 seconds (instead of default 5)
    },
    
    # Worker polling optimization
    # Increase the interval between worker polls to reduce Redis reads
    worker_hijack_root_logger=False,
    worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s',
    
    # Queue routing configuration
    # Routes tasks to specific queues based on CELERY_QUEUE_NAME environment variable
    task_routes={
        'api.tasks.optimize_resume_task': {
            'queue': queue_name,
        },
    },
    task_default_queue=queue_name,
    task_default_exchange='tasks',
    task_default_exchange_type='direct',
    task_default_routing_key=queue_name,
)

logger.info(f"Celery app configured with broker: {redis_url[:20]}...")

