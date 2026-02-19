"""Job endpoints backed by Postgres (source of truth)."""

import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from api.models import JobDetailAnalysis, JobStatusResponse
from api.database import get_db
from api.deps import CurrentUserIdentity, get_current_user_identity
from api.cache import (
    get_jobs_list_cache,
    set_jobs_list_cache,
    on_job_write_invalidate,
)
from api.job_repository import (
    InvalidCursorError,
    fetch_job_envelope_cached,
    get_job_for_user,
    list_jobs_for_user_cursor,
    serialize_job_for_list,
    update_job_status as repo_update_job_status,
)
from api.user_job_counts import decrement_active_jobs

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)
router = APIRouter()


_JobStatusLiteral = Literal["pending", "processing", "completed", "failed", "cancelled"]


@router.get("/jobs")
async def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: list[_JobStatusLiteral] | None = Query(default=None),
    identity: CurrentUserIdentity = Depends(get_current_user_identity),
    db: Session = Depends(get_db),
):
    user_id_str = str(identity.user_id)
    # Normalize: empty list or None → "all"; single/multiple → sorted comma-joined for cache key
    if not status:
        status_key = "all"
        status_filter: _JobStatusLiteral | list[_JobStatusLiteral] | None = None
    else:
        status_key = ",".join(sorted(set(status)))
        status_filter = list(status) if len(status) > 1 else status[0]

    cached = get_jobs_list_cache(user_id_str, status_key, limit, cursor)
    if cached:
        return cached

    try:
        jobs, next_cursor = list_jobs_for_user_cursor(
            db,
            user_id=identity.user_id,
            limit=limit,
            cursor=cursor,
            status=status_filter,
        )
    except InvalidCursorError:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    payload = {
        "items": [serialize_job_for_list(job) for job in jobs],
        "next_cursor": next_cursor,
    }
    set_jobs_list_cache(user_id_str, status_key, limit, cursor, payload)
    return payload


def _envelope_to_status_response(envelope: dict) -> JobStatusResponse:
    """Build JobStatusResponse from canonical envelope (exclude cache-internal and worker-only keys)."""
    out = {
        "job_id": envelope["job_id"],
        "status": envelope["status"],
        "created_at": envelope["created_at"],
        "completed_at": envelope.get("completed_at"),
        "error_message": envelope.get("error_message"),
        "company_name": envelope.get("company_name"),
        "result": envelope.get("result"),
        "original_latex": envelope.get("original_latex"),
        "optimizer_version": envelope.get("optimizer_version"),
        "llm_prompt_tokens": envelope.get("llm_prompt_tokens"),
        "llm_completion_tokens": envelope.get("llm_completion_tokens"),
        "llm_estimated_cost_usd": envelope.get("llm_estimated_cost_usd"),
        "llm_usage_source": envelope.get("llm_usage_source"),
    }
    analysis_raw = envelope.get("analysis_json")
    if isinstance(analysis_raw, dict):
        try:
            out["analysis"] = JobDetailAnalysis(**analysis_raw)
        except Exception:
            out["analysis"] = None
            out["analysis_parse_failed"] = True
    return JobStatusResponse(**out)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    identity: CurrentUserIdentity = Depends(get_current_user_identity),
    db: Session = Depends(get_db),
):
    envelope = fetch_job_envelope_cached(db, job_id, caller="user_detail")
    if not envelope:
        raise HTTPException(status_code=404, detail="Job not found")
    if envelope.get("owner_user_id") != str(identity.user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    return _envelope_to_status_response(envelope)


@router.get("/jobs/{job_id}/latex")
async def get_job_latex(
    job_id: str,
    identity: CurrentUserIdentity = Depends(get_current_user_identity),
    db: Session = Depends(get_db),
):
    envelope = fetch_job_envelope_cached(db, job_id, caller="user_detail")
    if not envelope:
        raise HTTPException(status_code=404, detail="Job not found")
    if envelope.get("owner_user_id") != str(identity.user_id):
        raise HTTPException(status_code=404, detail="Job not found")
    if envelope.get("status") not in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in a terminal state with result (status: {envelope.get('status')})",
        )
    result = envelope.get("result")
    optimized_latex = result.get("optimized_latex") if isinstance(result, dict) else None
    if not optimized_latex:
        raise HTTPException(status_code=404, detail="Optimized LaTeX not available for this job")
    return {
        "job_id": job_id,
        "latex": optimized_latex,
        "filename": (result.get("filename") if isinstance(result, dict) else None) or "resume.pdf",
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    identity: CurrentUserIdentity = Depends(get_current_user_identity),
    db: Session = Depends(get_db),
):
    job = get_job_for_user(db, job_id, identity.user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in ["pending", "processing"]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel job with status: {job.status}. Only pending or processing jobs can be cancelled.",
        )

    repo_update_job_status(
        db,
        job=job,
        status="cancelled",
        completed_at=datetime.now(timezone.utc),
        error_message="Job cancelled by user",
    )
    decrement_active_jobs(db, identity.user_id)
    db.commit()

    on_job_write_invalidate(str(identity.user_id), job_id)

    return {"job_id": job_id, "status": "cancelled"}


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job_endpoint(
    job_id: str,
    identity: CurrentUserIdentity = Depends(get_current_user_identity),
    db: Session = Depends(get_db),
):
    job = get_job_for_user(db, job_id, identity.user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in ["pending", "processing"]:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete job with status: {job.status}. Please cancel the job first.",
        )

    db.delete(job)
    db.commit()

    on_job_write_invalidate(str(identity.user_id), job_id)

    return Response(status_code=204)
