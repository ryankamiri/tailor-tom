"""Optimize endpoint for creating optimization jobs."""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.models import OptimizationRequest, OptimizationResponse
from api.database import get_db
from api.deps import get_current_user
from api.db_models import User
from api.job_repository import create_job, generate_job_id, get_job_by_id, update_job_status as repo_update_job_status
from api.cache import invalidate_user_job_list_cache, invalidate_user_profile_cache
from worker.tasks import optimize_resume_task
from tailor_tom.latex_compiler import validate_latex
from tailor_tom.config import settings
from tailor_tom.constants import DAILY_JOB_LIMIT

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)
router = APIRouter()


@router.post("/optimize", response_model=OptimizationResponse)
async def create_optimization_job(
    request: OptimizationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new optimization job."""

    is_valid, error_message = validate_latex(request.resume_latex)
    if not is_valid:
        logger.error(f"Invalid LaTeX in optimization request: {error_message}")
        raise HTTPException(status_code=400, detail=f"Invalid LaTeX: {error_message}")

    if len(request.job_description.strip()) < 50:
        logger.error(f"Job description too short: {len(request.job_description.strip())} characters")
        raise HTTPException(status_code=400, detail="Job description must be at least 50 characters")

    today_utc = datetime.now(timezone.utc).date()
    effective_completed = (
        0
        if (
            current_user.daily_completions_date is None
            or current_user.daily_completions_date < today_utc
        )
        else current_user.daily_completions_count
    )
    total_used = effective_completed + current_user.active_jobs_count
    if total_used >= DAILY_JOB_LIMIT:
        msg = (
            f"Daily limit reached. You have {effective_completed} completed and "
            f"{current_user.active_jobs_count} pending/processing jobs (limit: {DAILY_JOB_LIMIT})."
        )
        if effective_completed >= DAILY_JOB_LIMIT:
            msg = (
                f"Daily limit reached. You've completed {effective_completed} jobs today "
                f"(limit: {DAILY_JOB_LIMIT}). Please try again tomorrow."
            )
        raise HTTPException(status_code=403, detail=msg)

    job_id = generate_job_id(request.first_name, request.last_name)
    created_at = datetime.now(timezone.utc)

    create_job(
        db,
        job_id=job_id,
        user_id=current_user.id,
        original_latex=request.resume_latex,
        company_name=request.company_name,
        target_pages=request.target_pages,
        max_iterations=request.max_iterations or 3,
        job_description=request.job_description,
        first_name=request.first_name,
        last_name=request.last_name,
    )
    current_user.active_jobs_count += 1
    db.commit()

    invalidate_user_job_list_cache(str(current_user.id))
    invalidate_user_profile_cache(str(current_user.id))

    queue_name = settings.celery_queue_name
    try:
        optimize_resume_task.apply_async(
            kwargs={"job_id": job_id},
            queue=queue_name,
            priority=5,
        )
    except Exception as e:
        logger.exception(f"Failed to enqueue task for job {job_id} to queue '{queue_name}': {e}")
        job = get_job_by_id(db, job_id)
        if job:
            repo_update_job_status(
                db,
                job=job,
                status="failed",
                completed_at=datetime.now(timezone.utc),
                error_message="Failed to enqueue optimization task",
            )
            current_user.active_jobs_count = max(0, current_user.active_jobs_count - 1)
            db.commit()
            invalidate_user_job_list_cache(str(current_user.id))
            invalidate_user_profile_cache(str(current_user.id))
        raise HTTPException(status_code=500, detail="Failed to enqueue optimization task")

    return OptimizationResponse(
        job_id=job_id,
        status="pending",
        created_at=created_at.isoformat().replace('+00:00', 'Z'),
    )
