"""Celery tasks for TailorTom optimization jobs."""

import logging
from datetime import datetime, timezone
from api.celery_app import celery_app
from api.storage import update_job_status, get_job
from tailor_tom.optimizer import optimize_resume, configure_dspy
from tailor_tom.config import settings

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for Celery tasks


@celery_app.task(bind=True, name="api.tasks.optimize_resume_task")
def optimize_resume_task(
    self,
    job_id: str,
    resume_latex: str,
    job_description: str,
    target_pages: int,
    max_iterations: int | None,
    max_bullet_lines: int,
    first_name: str,
    last_name: str,
    company_name: str,
):
    """Celery task to optimize a resume.
    
    This task runs the optimization pipeline and updates job status in Redis.
    
    Args:
        job_id: Unique job identifier
        resume_latex: Original resume LaTeX content
        job_description: Job description to optimize for
        target_pages: Target number of pages
        max_iterations: Maximum optimization iterations
        max_bullet_lines: Maximum lines per bullet point
        first_name: User's first name for filename
        last_name: User's last name for filename
        company_name: Company name for filename
    """
    try:
        # Check if job was cancelled
        job = get_job(job_id)
        if not job:
            logger.error(f"[optimize_resume_task] Job {job_id} not found, skipping")
            return
        
        if job.get("status") == "failed" and job.get("error_message") == "Job cancelled by user":
            return
        
        # Update status to processing
        update_job_status(job_id, "processing")
        
        # Configure DSPy in this worker process (DSPy settings are process-local)
        configure_dspy()
        
        # Run optimization
        result = optimize_resume(
            resume_latex=resume_latex,
            job_description=job_description,
            target_pages=target_pages,
            max_iterations=max_iterations,
            max_bullet_lines=max_bullet_lines,
        )
        
        if result.success:
            # Generate filename using provided company name (Title_Case format)
            safe_first = first_name.strip().replace(" ", "_").replace("/", "_").title()
            safe_last = last_name.strip().replace(" ", "_").replace("/", "_").title()
            safe_company = company_name.strip().replace(" ", "_").replace("/", "_").title()
            filename = f"{safe_first}_{safe_last}_{safe_company}.pdf"
            
            # Update job with results
            update_job_status(
                job_id,
                "completed",
                completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                result={
                    "optimized_latex": result.optimized_latex,
                    "filename": filename,
                },
                company_name=company_name,
            )
        else:
            # Update job with error
            error_message = result.error_message or "Optimization failed"
            update_job_status(
                job_id,
                "failed",
                completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                error_message=error_message,
            )
            
            logger.error(f"[optimize_resume_task] Job {job_id} failed: {error_message}")
            
    except Exception as e:
        logger.exception(f"[optimize_resume_task] Error during optimization for job {job_id}")
        
        # Update job with error
        update_job_status(
            job_id,
            "failed",
            completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            error_message=str(e),
        )
        
        # Re-raise to trigger Celery retry
        raise

