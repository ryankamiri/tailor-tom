"""Redis storage for DOCX conversion jobs (used by API routes and Celery task)."""

from typing import Optional

import redis

from tailor_tom.config import settings

CONVERSION_KEY_PREFIX = "conversion:"
CONVERSION_TTL = 3600  # 1 hour

_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Get or create a Redis client for conversion jobs."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client
