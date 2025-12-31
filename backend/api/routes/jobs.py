"""Job status endpoints."""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from api.models import JobStatusResponse
from api.storage import get_job, update_job_status, delete_job
from api.celery_app import celery_app

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for API endpoints
router = APIRouter()


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """Get the status of an optimization job."""
    
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        created_at=job["created_at"],
        completed_at=job.get("completed_at"),
        error_message=job.get("error_message"),
        company_name=job.get("company_name"),
        result=job.get("result"),
    )


@router.get("/jobs/{job_id}/latex")
async def get_job_latex(job_id: str):
    """Get the optimized LaTeX for a completed job."""
    
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {job['status']})",
        )
    
    result = job.get("result")
    if not result:
        raise HTTPException(status_code=500, detail="Job result not available")
    
    return {
        "job_id": job_id,
        "latex": result.get("optimized_latex"),
        "filename": result.get("filename"),
    }


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a pending or processing job."""
    
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job["status"] not in ["pending", "processing"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status: {job['status']}. Only pending or processing jobs can be cancelled.",
        )
    
    # Try to revoke the Celery task if it's still pending
    try:
        # Get the task ID from Celery (if available)
        # Note: We'd need to store task_id with the job to revoke it properly
        # For now, we'll just mark it as cancelled and let the task check the status
        pass
    except Exception as e:
        logger.error(f"Failed to revoke Celery task for job {job_id}: {e}")
    
    # Update job status to cancelled
    update_job_status(
        job_id,
        "failed",
        completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        error_message="Job cancelled by user",
    )
    
    return {"job_id": job_id, "status": "failed", "message": "Job cancelled successfully"}


@router.delete("/jobs/{job_id}")
async def delete_job_endpoint(job_id: str):
    """Delete a job (idempotent - returns 200 even if job doesn't exist)."""
    
    job = get_job(job_id)
    if not job:
        # Job doesn't exist - return success (idempotent operation)
        return {"job_id": job_id, "message": "Job deleted successfully"}
    
    if job["status"] in ["pending", "processing"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete job with status: {job['status']}. Please cancel the job first.",
        )
    
    # Delete job from Redis
    delete_job(job_id)
    
    return {"job_id": job_id, "message": "Job deleted successfully"}

