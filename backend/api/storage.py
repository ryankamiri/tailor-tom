"""Redis-based job storage for the API."""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import redis
from tailor_tom.config import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors

# Redis client instance
_redis_client: Optional[redis.Redis] = None


def get_redis_client() -> redis.Redis:
    """Get or create Redis client instance."""
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True,
            )
            # Test connection
            _redis_client.ping()
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    return _redis_client


def _get_job_key(job_id: str) -> str:
    """Get Redis key for a job."""
    return f"job:{job_id}"


def create_job(job_id: str, job_data: Dict[str, Any]) -> None:
    """Create a new job in Redis.
    
    Args:
        job_id: Unique job identifier
        job_data: Job data dictionary with fields:
            - status: "pending" | "processing" | "completed" | "failed"
            - created_at: ISO timestamp string
            - completed_at: ISO timestamp string | None
            - error_message: string | None
            - original_latex: string
            - result: dict | None (with optimized_latex and filename)
            - company_name: string
            - target_pages: int
            - max_iterations: int
    """
    client = get_redis_client()
    key = _get_job_key(job_id)
    
    # Convert result dict to JSON string for storage
    # Also convert None values to empty strings (Redis doesn't accept None)
    job_data_copy = {}
    for field, value in job_data.items():
        if value is None:
            job_data_copy[field] = ""  # Convert None to empty string
        elif field == "result" and isinstance(value, dict):
            job_data_copy[field] = json.dumps(value)
        else:
            job_data_copy[field] = str(value)
    
    # Set TTL (7 days default)
    ttl_seconds = settings.redis_ttl_days * 24 * 60 * 60
    
    # Store as hash
    client.hset(key, mapping=job_data_copy)
    client.expire(key, ttl_seconds)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """Get a job from Redis.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        Job data dictionary or None if not found
    """
    client = get_redis_client()
    key = _get_job_key(job_id)
    
    job_data = client.hgetall(key)
    if not job_data:
        return None
    
    # Convert empty strings back to None (we stored None as "" in create_job)
    # Handle all optional fields that could be None
    optional_string_fields = ["result", "completed_at", "error_message", "company_name"]
    for field in optional_string_fields:
        if job_data.get(field) == "":
            job_data[field] = None
    
    # Convert result JSON string back to dict (if it exists and is not None)
    if job_data.get("result"):
        try:
            job_data["result"] = json.loads(job_data["result"])
        except json.JSONDecodeError:
            logger.error(f"Failed to parse result JSON for job {job_id}")
            job_data["result"] = None
    
    # Convert numeric fields (handle empty strings safely)
    if job_data.get("target_pages"):
        try:
            job_data["target_pages"] = int(job_data["target_pages"])
        except (ValueError, TypeError):
            logger.error(f"Invalid target_pages value for job {job_id}: {job_data.get('target_pages')}")
            job_data["target_pages"] = 1  # Default fallback
    
    if job_data.get("max_iterations"):
        try:
            job_data["max_iterations"] = int(job_data["max_iterations"])
        except (ValueError, TypeError):
            logger.error(f"Invalid max_iterations value for job {job_id}: {job_data.get('max_iterations')}")
            job_data["max_iterations"] = 3  # Default fallback
    
    return job_data


def update_job_status(
    job_id: str,
    status: str,
    **updates: Any
) -> None:
    """Update job status and other fields in Redis.
    
    Args:
        job_id: Unique job identifier
        status: New status ("pending" | "processing" | "completed" | "failed")
        **updates: Additional fields to update (e.g., completed_at, error_message, result)
    """
    client = get_redis_client()
    key = _get_job_key(job_id)
    
    # Check if job exists
    if not client.exists(key):
        logger.error(f"Attempted to update non-existent job {job_id}")
        return
    
    # Update status
    client.hset(key, "status", status)
    
    # Update additional fields
    for field, value in updates.items():
        if value is None:
            client.hset(key, field, "")
        elif field == "result" and isinstance(value, dict):
            # Convert result dict to JSON string
            client.hset(key, field, json.dumps(value))
        else:
            client.hset(key, field, str(value))


def delete_job(job_id: str) -> bool:
    """Delete a job from Redis.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        True if job was deleted, False if it didn't exist
    """
    client = get_redis_client()
    key = _get_job_key(job_id)
    
    deleted = client.delete(key)
    return deleted > 0
