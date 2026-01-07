"""Redis-based job storage for the API."""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Tuple
from threading import Lock
import redis
from tailor_tom.config import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors

# Redis client instance
_redis_client: Optional[redis.Redis] = None

# In-memory cache for job status to reduce Redis reads
# Cache TTL: 30 seconds (job status doesn't change frequently)
_JOB_CACHE_TTL = 30  # seconds
_job_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}  # {job_id: (job_data, timestamp)}
_cache_lock = Lock()


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
    """Get a job from Redis with in-memory caching to reduce Redis reads.
    
    Caches job data for 30 seconds to reduce redundant Redis operations.
    Cache is automatically invalidated when job status is updated.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        Job data dictionary or None if not found
    """
    # Check cache first
    current_time = time.time()
    with _cache_lock:
        if job_id in _job_cache:
            cached_data, cache_time = _job_cache[job_id]
            if current_time - cache_time < _JOB_CACHE_TTL:
                # Cache hit - return cached data
                return cached_data.copy()  # Return copy to prevent mutation
            else:
                # Cache expired - remove it
                del _job_cache[job_id]
    
    # Cache miss or expired - fetch from Redis
    client = get_redis_client()
    key = _get_job_key(job_id)
    
    job_data = client.hgetall(key)
    if not job_data:
        return None
    
    # Convert empty strings back to None (we stored None as "" in create_job)
    # Handle all optional fields that could be None
    # Note: job_description, first_name, last_name are required and should not be None
    optional_string_fields = ["result", "completed_at", "error_message"]
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
            max_iter = int(job_data["max_iterations"])
            job_data["max_iterations"] = max_iter if max_iter > 0 else None
        except (ValueError, TypeError):
            logger.error(f"Invalid max_iterations value for job {job_id}: {job_data.get('max_iterations')}")
            job_data["max_iterations"] = None
    
    if job_data.get("max_bullet_lines"):
        try:
            job_data["max_bullet_lines"] = int(job_data["max_bullet_lines"])
        except (ValueError, TypeError):
            job_data["max_bullet_lines"] = 2  # Default fallback
    
    # Store in cache
    with _cache_lock:
        _job_cache[job_id] = (job_data.copy(), current_time)
        # Clean up old cache entries (keep cache size reasonable)
        if len(_job_cache) > 1000:
            # Remove oldest 20% of entries
            sorted_entries = sorted(_job_cache.items(), key=lambda x: x[1][1])
            for old_job_id, _ in sorted_entries[:200]:
                del _job_cache[old_job_id]
    
    return job_data


def update_job_status(
    job_id: str,
    status: str,
    **updates: Any
) -> None:
    """Update job status and other fields in Redis.
    
    Also invalidates the in-memory cache for this job to ensure fresh data.
    
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
    
    # Invalidate cache for this job
    with _cache_lock:
        if job_id in _job_cache:
            del _job_cache[job_id]


def delete_job(job_id: str) -> bool:
    """Delete a job from Redis.
    
    Also removes the job from the in-memory cache.
    
    Args:
        job_id: Unique job identifier
        
    Returns:
        True if job was deleted, False if it didn't exist
    """
    client = get_redis_client()
    key = _get_job_key(job_id)
    
    deleted = client.delete(key)
    
    # Remove from cache
    with _cache_lock:
        if job_id in _job_cache:
            del _job_cache[job_id]
    
    return deleted > 0


def get_orphaned_processing_jobs() -> list[Dict[str, Any]]:
    """Get all jobs with status 'processing' (orphaned after worker restart).
    
    Returns:
        List of job dictionaries with all fields needed to re-enqueue
    """
    client = get_redis_client()
    
    # Scan for all job keys
    orphaned_jobs = []
    cursor = 0
    pattern = "job:*"
    
    while True:
        cursor, keys = client.scan(cursor, match=pattern, count=100)
        for key in keys:
            # Extract job_id from key (format: "job:{job_id}")
            job_id = key[4:]  # Remove "job:" prefix
            
            # First check status directly from Redis (bypass cache)
            # This ensures we get the actual current status
            raw_status = client.hget(key, "status")
            if raw_status != "processing":
                continue
            
            # Now use get_job() to get full job data with proper parsing
            # Clear cache first to ensure fresh data
            with _cache_lock:
                if job_id in _job_cache:
                    del _job_cache[job_id]
            
            job_data = get_job(job_id)
            if not job_data:
                continue
            
            # Double-check status (should be "processing" but verify)
            if job_data.get("status") == "processing":
                # Ensure job_id is in the dict (get_job doesn't add it)
                job_data["job_id"] = job_id
                orphaned_jobs.append(job_data)
        
        if cursor == 0:
            break
    
    return orphaned_jobs
