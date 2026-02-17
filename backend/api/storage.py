"""Compatibility storage module.

Redis remains the transport/cache layer, while optimization job persistence is DB-first.
This module keeps legacy helper signatures used by worker/optimizer/auth.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import redis

from api.cache import (
    get_redis_client as _cache_redis_client,
    on_job_write_invalidate,
    set_job_cache,
)
from api.database import SessionLocal
from api.db_models import Job
from api.job_repository import (
    create_job as repo_create_job,
    get_global_stats,
    get_job_by_id,
    get_job_status_by_id as repo_get_job_status_by_id,
    list_processing_jobs_for_recovery,
    list_stuck_pending_jobs_for_recovery,
    serialize_job_for_detail,
    update_job_status as repo_update_job_status,
)
from tailor_tom.config import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)


# ---------------------------------------------------------------------------
# Redis client (used for refresh token and any cache helpers)
# ---------------------------------------------------------------------------

def get_redis_client() -> redis.Redis:
    return _cache_redis_client()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None


def _job_to_legacy_dict(job: Job) -> dict[str, Any]:
    detail = serialize_job_for_detail(job)
    detail.update(
        {
            "job_description": job.job_description,
            "max_bullet_lines": job.max_bullet_lines,
            "first_name": job.first_name,
            "last_name": job.last_name,
            "original_latex": job.original_latex,
            "target_pages": job.target_pages,
            "max_iterations": job.max_iterations,
            "restart_count": str(job.restart_count),
            "last_restart_time": (
                job.last_restart_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                if job.last_restart_time
                else ""
            ),
            "user_id": str(job.user_id),
        }
    )
    return detail


def _apply_result_updates(job: Job, updates: dict[str, Any]) -> dict[str, Any]:
    result = updates.get("result")
    transformed: dict[str, Any] = {}
    if isinstance(result, dict):
        optimized_latex = result.get("optimized_latex") or ""
        transformed["optimized_latex"] = optimized_latex
        transformed["result_filename"] = result.get("filename") or "resume.pdf"
        transformed["original_latex_length"] = len(job.original_latex or "")
        transformed["optimized_latex_length"] = len(optimized_latex)
    return transformed


# ---------------------------------------------------------------------------
# Legacy-compatible job helpers (DB-backed)
# ---------------------------------------------------------------------------

def create_job(job_id: str, job_data: dict[str, Any]) -> None:
    db = SessionLocal()
    try:
        user_id = job_data.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        repo_create_job(
            db,
            job_id=job_id,
            user_id=UUID(user_id),
            original_latex=job_data["original_latex"],
            company_name=job_data.get("company_name"),
            target_pages=int(job_data.get("target_pages") or 1),
            max_iterations=int(job_data.get("max_iterations") or 3),
            job_description=job_data["job_description"],
            max_bullet_lines=int(job_data.get("max_bullet_lines") or 2),
            first_name=job_data["first_name"],
            last_name=job_data["last_name"],
        )
        db.commit()
    finally:
        db.close()


def get_job_status_only(job_id: str) -> Optional[str]:
    """Lightweight status-only check (e.g. for cancellation). Does not load full job payload."""
    db = SessionLocal()
    try:
        return repo_get_job_status_by_id(db, job_id)
    finally:
        db.close()


def get_job(job_id: str) -> Optional[dict[str, Any]]:
    cached = _cache_redis_client().get(f"cache:job:{job_id}")
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass

    db = SessionLocal()
    try:
        job = get_job_by_id(db, job_id)
        if not job:
            return None
        payload = _job_to_legacy_dict(job)
        set_job_cache(job_id, payload)
        return payload
    finally:
        db.close()


def update_job_status(job_id: str, status: str, **updates: Any) -> None:
    db = SessionLocal()
    try:
        job = get_job_by_id(db, job_id)
        if not job:
            logger.error(f"Attempted to update non-existent job {job_id}")
            return

        transformed = _apply_result_updates(job, updates)
        completed_at = _parse_iso_dt(updates.get("completed_at"))
        last_restart_time = _parse_iso_dt(updates.get("last_restart_time"))
        restart_count_raw = updates.get("restart_count")
        restart_count = int(restart_count_raw) if restart_count_raw is not None else None

        repo_update_job_status(
            db,
            job=job,
            status=status,
            completed_at=completed_at,
            error_message=updates.get("error_message"),
            company_name=updates.get("company_name"),
            optimized_latex=transformed.get("optimized_latex"),
            result_filename=transformed.get("result_filename"),
            original_latex_length=transformed.get("original_latex_length"),
            optimized_latex_length=transformed.get("optimized_latex_length"),
            restart_count=restart_count,
            last_restart_time=last_restart_time,
            analysis_json=updates.get("analysis_json"),
            llm_usage_source=updates.get("llm_usage_source"),
            llm_prompt_tokens=updates.get("llm_prompt_tokens"),
            llm_completion_tokens=updates.get("llm_completion_tokens"),
            llm_estimated_cost_usd=updates.get("llm_estimated_cost_usd"),
        )
        db.commit()

        on_job_write_invalidate(str(job.user_id), job_id)
    finally:
        db.close()


def delete_job(job_id: str) -> bool:
    db = SessionLocal()
    try:
        job = get_job_by_id(db, job_id)
        if not job:
            return False
        user_id = str(job.user_id)
        db.delete(job)
        db.commit()
        on_job_write_invalidate(user_id, job_id)
        return True
    finally:
        db.close()


def get_orphaned_processing_jobs() -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        return [_job_to_legacy_dict(job) for job in list_processing_jobs_for_recovery(db)]
    finally:
        db.close()


def get_stuck_pending_jobs(min_age_seconds: int = 120) -> list[dict[str, Any]]:
    """Jobs stuck in pending (task likely never enqueued or lost)."""
    db = SessionLocal()
    try:
        jobs = list_stuck_pending_jobs_for_recovery(db, min_age_seconds=min_age_seconds)
        return [_job_to_legacy_dict(job) for job in jobs]
    finally:
        db.close()


def get_job_stats() -> dict[str, int]:
    db = SessionLocal()
    try:
        return get_global_stats(db)
    finally:
        db.close()
