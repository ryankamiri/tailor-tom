"""Redis cache helpers (cache-aside) for jobs and user profile."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

import redis

from tailor_tom.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[redis.Redis] = None

JOB_CACHE_TTL_SECONDS = 10 * 60
JOB_LIST_CACHE_TTL_SECONDS = 90
USER_PROFILE_CACHE_TTL_SECONDS = 10 * 60
ADMIN_USER_COSTS_CACHE_TTL_SECONDS = 900  # 15 min

# Canonical job envelope: all readers (user detail, admin detail, worker) use this shape.
CACHE_SCHEMA_VERSION = 2
JOB_ENVELOPE_KEY_PREFIX = "cache:job:"


def get_redis_client() -> redis.Redis:
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


def _safe_json_loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(value)


def get_job_envelope_cache(job_id: str) -> dict[str, Any] | None:
    """Return canonical job envelope or None (miss, invalid schema, or Redis error). Fail-open."""
    try:
        key = f"{JOB_ENVELOPE_KEY_PREFIX}{job_id}"
        raw = get_redis_client().get(key)
        data = _safe_json_loads(raw)
        if not isinstance(data, dict):
            return None
        if data.get("cache_schema_version") != CACHE_SCHEMA_VERSION:
            return None
        if data.get("job_id") is None or data.get("owner_user_id") is None:
            return None
        return data
    except Exception as e:
        logger.warning("Job envelope cache get failed for job_id=%s: %s", job_id, e)
        return None


def set_job_envelope_cache(job_id: str, payload: dict[str, Any]) -> None:
    """Write canonical job envelope. Fail-open on Redis error (log only)."""
    try:
        key = f"{JOB_ENVELOPE_KEY_PREFIX}{job_id}"
        get_redis_client().setex(key, JOB_CACHE_TTL_SECONDS, _safe_json_dumps(payload))
    except Exception as e:
        logger.warning("Job envelope cache set failed for job_id=%s: %s", job_id, e)


def get_jobs_list_cache(user_id: str, status: str, limit: int, cursor: str | None) -> dict[str, Any] | None:
    cursor_key = cursor or "first"
    key = f"cache:jobs:user:{user_id}:status:{status}:limit:{limit}:cursor:{cursor_key}"
    raw = get_redis_client().get(key)
    data = _safe_json_loads(raw)
    return data if isinstance(data, dict) else None


def set_jobs_list_cache(
    user_id: str,
    status: str,
    limit: int,
    cursor: str | None,
    payload: dict[str, Any],
) -> None:
    cursor_key = cursor or "first"
    key = f"cache:jobs:user:{user_id}:status:{status}:limit:{limit}:cursor:{cursor_key}"
    get_redis_client().setex(key, JOB_LIST_CACHE_TTL_SECONDS, _safe_json_dumps(payload))


def get_user_profile_cache(user_id: str) -> dict[str, Any] | None:
    key = f"cache:user:{user_id}:profile"
    raw = get_redis_client().get(key)
    data = _safe_json_loads(raw)
    return data if isinstance(data, dict) else None


def set_user_profile_cache(user_id: str, payload: dict[str, Any]) -> None:
    key = f"cache:user:{user_id}:profile"
    get_redis_client().setex(key, USER_PROFILE_CACHE_TTL_SECONDS, _safe_json_dumps(payload))


def invalidate_job_cache(job_id: str) -> None:
    """Single key for job detail; used by on_job_write_invalidate."""
    try:
        get_redis_client().delete(f"{JOB_ENVELOPE_KEY_PREFIX}{job_id}")
    except Exception as e:
        logger.warning("Job cache invalidate failed for job_id=%s: %s", job_id, e)


def invalidate_user_profile_cache(user_id: str) -> None:
    get_redis_client().delete(f"cache:user:{user_id}:profile")


def invalidate_user_job_list_cache(user_id: str) -> None:
    rc = get_redis_client()
    pattern = f"cache:jobs:user:{user_id}:*"
    cursor = 0
    keys_to_delete: list[str] = []
    while True:
        cursor, keys = rc.scan(cursor=cursor, match=pattern, count=200)
        if keys:
            keys_to_delete.extend(keys)
        if cursor == 0:
            break
    if keys_to_delete:
        rc.delete(*keys_to_delete)


def invalidate_job_related_cache(user_id: str, job_id: str, include_profile: bool = True) -> None:
    """Invalidate job detail, user jobs list, and optionally user profile (active count changed)."""
    invalidate_job_cache(job_id)
    invalidate_user_job_list_cache(user_id)
    if include_profile:
        invalidate_user_profile_cache(user_id)


def on_job_write_invalidate(user_id: str, job_id: str, include_profile: bool = True) -> None:
    """Single entry point for cache invalidation after any job-affecting write.
    Use from routes and storage: invalidates job/list/profile caches and admin user-costs cache.
    Fail-open on Redis errors (log only)."""
    try:
        invalidate_job_related_cache(user_id, job_id, include_profile=include_profile)
        invalidate_admin_user_costs_cache()
    except Exception as e:
        logger.warning("Job write invalidation failed: %s", e)


# ---------------------------------------------------------------------------
# Admin user-costs cache (cache-aside, invalidate on job write)
# ---------------------------------------------------------------------------

def _admin_user_costs_cache_key(year: int, month: int, page: int, limit: int) -> str:
    """Normalized key: month zero-padded for consistency."""
    mm = f"{month:02d}"
    return f"cache:admin:user-costs:year:{year}:month:{mm}:page:{page}:limit:{limit}"


def get_admin_user_costs_cache(year: int, month: int, page: int, limit: int) -> dict[str, Any] | None:
    """Return cached payload or None (cache miss or Redis error; fail-open)."""
    try:
        key = _admin_user_costs_cache_key(year, month, page, limit)
        raw = get_redis_client().get(key)
        data = _safe_json_loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("Admin user-costs cache get failed: %s", e)
        return None


def cache_get_or_set_dict(
    get_fn: Callable[..., dict[str, Any] | None],
    set_fn: Callable[..., None],
    producer: Callable[[], dict[str, Any]],
    *key_args: Any,
) -> dict[str, Any]:
    """Cache-aside: return cached dict if present, else call producer(), set cache, return. Fail-open on set."""
    cached = get_fn(*key_args)
    if cached is not None:
        return cached
    payload = producer()
    try:
        set_fn(*key_args, payload)
    except Exception as e:
        logger.warning("Cache set failed: %s", e)
    return payload


def set_admin_user_costs_cache(
    year: int, month: int, page: int, limit: int, payload: dict[str, Any]
) -> None:
    """Cache full response; on Redis error log and skip (fail-open)."""
    try:
        key = _admin_user_costs_cache_key(year, month, page, limit)
        get_redis_client().setex(
            key, ADMIN_USER_COSTS_CACHE_TTL_SECONDS, _safe_json_dumps(payload)
        )
    except Exception as e:
        logger.warning("Admin user-costs cache set failed: %s", e)


def invalidate_admin_user_costs_cache() -> None:
    """Invalidate all admin user-costs cache keys (pattern scan + batch delete). Fail-open."""
    try:
        rc = get_redis_client()
        pattern = "cache:admin:user-costs:*"
        cursor = 0
        keys_to_delete: list[str] = []
        while True:
            cursor, keys = rc.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                keys_to_delete.extend(keys)
            if cursor == 0:
                break
        if keys_to_delete:
            rc.delete(*keys_to_delete)
    except Exception as e:
        logger.warning("Admin user-costs cache invalidate failed: %s", e)
