"""Optimize endpoint for creating optimization jobs."""

import hashlib
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from api.models import OptimizationRequest, OptimizationResponse
from api.storage import create_job, update_job_status
from api.tasks import optimize_resume_task
from tailor_tom.latex_compiler import validate_latex
from tailor_tom.config import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for API endpoints
router = APIRouter()


def generate_job_id(first_name: str, last_name: str) -> str:
    """Generate a unique job ID from name and timestamp."""
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    combined = f"{timestamp}_{first_name}_{last_name}"
    return hashlib.md5(combined.encode()).hexdigest()[:16]




@router.post("/optimize", response_model=OptimizationResponse)
async def create_optimization_job(
    request: OptimizationRequest,
):
    """Create a new optimization job."""
    
    # Validate LaTeX compiles (quick check)
    is_valid, error_message = validate_latex(request.resume_latex)
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid LaTeX: {error_message}",
        )
    
    # Validate job description
    if len(request.job_description.strip()) < 50:
        raise HTTPException(
            status_code=400,
            detail="Job description must be at least 50 characters",
        )
    
    # Generate job ID
    job_id = generate_job_id(request.first_name, request.last_name)
    
    # Create job in Redis
    created_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    create_job(
        job_id,
        {
            "status": "pending",
            "created_at": created_at,
            "completed_at": None,
            "error_message": None,
            "original_latex": request.resume_latex,
            "result": None,
            "company_name": request.company_name,
            "target_pages": request.target_pages,
            "max_iterations": request.max_iterations,
        }
    )
    
    # Enqueue optimization task to Celery
    # Route to queue based on CELERY_QUEUE_NAME environment variable
    # This ensures local backend routes to local worker, hosted backend routes to hosted worker
    queue_name = settings.celery_queue_name
    try:
        task_result = optimize_resume_task.apply_async(
            args=[],
            kwargs={
                'job_id': job_id,
                'resume_latex': request.resume_latex,
                'job_description': request.job_description,
                'target_pages': request.target_pages,
                'max_iterations': request.max_iterations,
                'max_bullet_lines': request.max_bullet_lines,
                'first_name': request.first_name,
                'last_name': request.last_name,
                'company_name': request.company_name,
            },
            queue=queue_name,
        )
    except Exception as e:
        logger.exception(f"Failed to enqueue task for job {job_id} to queue '{queue_name}': {e}")
        # Update job status to failed
        update_job_status(
            job_id,
            "failed",
            completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            error_message=f"Failed to enqueue task: {str(e)}",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to enqueue optimization task: {str(e)}",
        )
    
    
    return OptimizationResponse(
        job_id=job_id,
        status="pending",
        created_at=created_at,
    )

