"""Celery tasks for TailorTom optimization jobs."""

import gc
import logging
import os
import sys
from datetime import datetime, timezone

from billiard.exceptions import TimeLimitExceeded
from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import worker_ready

from api.celery_app import celery_app
from api.job_fields import JOB_REENQUEUE_REQUIRED_FIELDS, JOB_RESTART_COUNT_FIELD, JOB_LAST_RESTART_TIME_FIELD
from api.storage import update_job_status, get_job, get_orphaned_processing_jobs
from tailor_tom.config import settings
from tailor_tom.optimizer import optimize_resume, configure_dspy

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for Celery tasks


@worker_ready.connect
def configure_worker(sender, **kwargs):
    """Configure worker on startup.
    
    Configures DSPy globally for the worker process and recovers orphaned jobs.
    If DSPy configuration fails, the worker will crash (as it should).
    """
    # Configure DSPy globally for this worker process
    # DSPy settings are process-local, so configure once when worker starts
    # If this fails, let it crash - worker cannot function without DSPy
    configure_dspy()
    
    # Recover orphaned 'processing' jobs
    try:
        # Get all jobs stuck in 'processing' state
        orphaned_jobs = get_orphaned_processing_jobs()
        
        if not orphaned_jobs:
            return
        
        logger.error(f"[worker_ready] Found {len(orphaned_jobs)} orphaned 'processing' jobs, re-enqueuing...")
        
        queue_name = settings.celery_queue_name
        re_enqueued = 0
        
        for job_data in orphaned_jobs:
            job_id = job_data.get("job_id")
            if not job_id:
                continue
            
            # Check restart count - fail after 3 attempts
            restart_count = int(job_data.get(JOB_RESTART_COUNT_FIELD, "0"))
            last_restart_time = job_data.get(JOB_LAST_RESTART_TIME_FIELD, "")
            
            if restart_count >= 3:
                logger.error(
                    f"[worker_ready] Job {job_id} has been restarted {restart_count} times. "
                    f"Marking as failed to prevent infinite loop."
                )
                update_job_status(
                    job_id,
                    "failed",
                    completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    error_message=(
                        "Job failed after multiple worker restarts. "
                        "This may indicate a memory issue or job complexity exceeding system limits. "
                        "Please try again with a simpler resume or contact support."
                    ),
                    result={
                        "optimized_latex": "",
                        "filename": "resume.pdf",
                        "error_details": {
                            "iterations": 0,
                            "optimized_latex_available": False,
                            "original_latex_length": 0,
                            "optimized_latex_length": 0,
                        }
                    },
                )
                continue
            
            # Check cooldown period (5 minutes)
            if last_restart_time:
                try:
                    last_restart_dt = datetime.fromisoformat(last_restart_time.replace('Z', '+00:00'))
                    time_since_restart = (datetime.now(timezone.utc) - last_restart_dt).total_seconds()
                    if time_since_restart < 300:  # 5 minutes
                        logger.error(
                            f"[worker_ready] Job {job_id} was restarted {time_since_restart:.0f}s ago. "
                            f"Skipping re-enqueue (cooldown period)."
                        )
                        continue
                except (ValueError, AttributeError):
                    # Invalid timestamp, proceed with re-enqueue
                    pass
            
            # Check if we have all required fields to re-enqueue
            # Note: company_name is optional (can be None or empty string)
            # Check for missing required fields (None, empty string, or not present)
            # For string fields, check if they're None or empty string
            # For numeric fields, check if they're None (0 is a valid value)
            missing_fields = []
            for field in JOB_REENQUEUE_REQUIRED_FIELDS:
                value = job_data.get(field)
                if value is None:
                    missing_fields.append(field)
                elif isinstance(value, str) and value.strip() == "":
                    missing_fields.append(field)
                elif field == "max_bullet_lines" and (not isinstance(value, int) or value <= 0):
                    # max_bullet_lines must be a positive integer
                    missing_fields.append(field)
                elif field == "target_pages" and (not isinstance(value, int) or value <= 0):
                    # target_pages must be a positive integer
                    missing_fields.append(field)
            
            if missing_fields:
                # Log the actual values to help debug - show full job data
                logger.error(
                    f"[worker_ready] Job {job_id} missing required fields {missing_fields}. "
                    f"Available fields: {list(job_data.keys())}. "
                    f"Full job data: {job_data}"
                )
            
            # company_name is optional, but if present it should be a string (can be empty)
            # We'll pass None if it's missing or empty
            
            if missing_fields:
                logger.error(
                    f"[worker_ready] Cannot re-enqueue job {job_id}: missing required fields {missing_fields}. "
                    f"Marking as failed - job data is incomplete and cannot be recovered. "
                    f"This may indicate a bug in job creation or Redis storage."
                )
                # Mark as failed - job is missing required data, cannot be processed
                update_job_status(
                    job_id,
                    "failed",
                    completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    error_message=f"Job cannot be recovered: missing required fields ({', '.join(missing_fields)}). The job data is incomplete and cannot be processed.",
                    result={
                        "optimized_latex": "",
                        "filename": "resume.pdf",
                        "error_details": {
                            "iterations": 0,
                            "optimized_latex_available": False,
                            "original_latex_length": 0,
                            "optimized_latex_length": 0,
                    }
                },
            )
                continue
            
            try:
                # Increment restart counter
                new_restart_count = restart_count + 1
                
                # Re-enqueue the task with all stored parameters
                optimize_resume_task.apply_async(
                    args=[],
                    kwargs={
                        'job_id': job_id,
                        'resume_latex': job_data["original_latex"],
                        'job_description': job_data["job_description"],
                        'target_pages': job_data["target_pages"],
                        'max_iterations': job_data.get("max_iterations"),
                        'max_bullet_lines': job_data["max_bullet_lines"],
                        'first_name': job_data["first_name"],
                        'last_name': job_data["last_name"],
                        'company_name': job_data.get("company_name") or None,  # Optional field
                    },
                    queue=queue_name,
                )
                
                # Reset status to pending and update restart tracking
                update_job_status(
                    job_id,
                    "pending",
                    **{
                        JOB_RESTART_COUNT_FIELD: str(new_restart_count),
                        JOB_LAST_RESTART_TIME_FIELD: datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    },
                )
                re_enqueued += 1
                
            except Exception as e:
                logger.error(f"[worker_ready] Failed to re-enqueue job {job_id}: {e}")
                # Still reset to pending in case task is in queue
                update_job_status(job_id, "pending")
        
        if re_enqueued > 0:
            logger.error(f"[worker_ready] Successfully re-enqueued {re_enqueued} orphaned jobs")
    
    except Exception as e:
        # Don't let recovery errors prevent worker from starting
        logger.error(f"[worker_ready] Error during orphaned job recovery: {e}")


def _on_task_failure(self, exc, task_id, args, kwargs, einfo):
    """Callback when task fails (including timeouts and crashes).
    
    This is called when the task fails, ensuring the job status is updated to 'failed'.
    Note: SIGKILL (hard timeout) may not trigger this reliably, but SoftTimeLimitExceeded will.
    """
    try:
        # Extract job_id from kwargs (task is called with args=[] and all params in kwargs)
        job_id = None
        if kwargs and 'job_id' in kwargs:
            job_id = kwargs['job_id']
        elif args and len(args) > 0:
            # Fallback to args if kwargs not available
            job_id = args[0]
        
        if job_id:
            # Check if job is already marked as failed (avoid duplicate updates)
            job = get_job(job_id)
            if job and job.get("status") != "failed":
                # Determine error message based on exception type
                if isinstance(exc, (TimeLimitExceeded, SoftTimeLimitExceeded)):
                    error_message = f"Task timed out after {settings.celery_task_time_limit} seconds"
                elif exc:
                    error_message = f"Task failed: {str(exc)}"
                else:
                    error_message = "Task failed (timeout or crash)"
                
                logger.error(f"[optimize_resume_task] Task {task_id} failed for job {job_id}: {error_message}")
                
                # Store any available result data (even if partial)
                result_data = None
                if job.get("result"):
                    # Preserve existing result if available
                    try:
                        import json
                        existing_result = job.get("result")
                        if isinstance(existing_result, str):
                            existing_result = json.loads(existing_result)
                        result_data = existing_result
                    except:
                        pass
                
                # If no result data, provide default structure
                if not result_data:
                    result_data = {
                        "optimized_latex": "",
                        "filename": "resume.pdf",
                        "error_details": {
                            "iterations": 0,
                            "optimized_latex_available": False,
                            "original_latex_length": 0,
                            "optimized_latex_length": 0,
                        }
                    }
                
                update_job_status(
                    job_id,
                    "failed",
                    completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                    error_message=error_message,
                    result=result_data,
                )
    except Exception as e:
        logger.error(f"[optimize_resume_task] Error in failure callback: {e}")


@celery_app.task(bind=True, name="api.tasks.optimize_resume_task", on_failure=_on_task_failure)
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
        
        # Configure DSPy (idempotent - only configures if not already configured)
        # This ensures DSPy is configured even if worker_ready signal didn't fire
        # or if worker process restarted (worker_max_tasks_per_child=50)
        configure_dspy()
        
        # Run optimization
        # Status will be updated to "processing" at the start of Phase 1 (actual work begins)
        result = optimize_resume(
            resume_latex=resume_latex,
            job_description=job_description,
            target_pages=target_pages,
            max_iterations=max_iterations,
            max_bullet_lines=max_bullet_lines,
            job_id=job_id,  # Pass job_id so optimizer can update status when work actually starts
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
            
            # Explicit cleanup of large objects
            if hasattr(result, 'pdf_bytes') and result.pdf_bytes:
                del result.pdf_bytes
            
            del resume_latex
            del job_description
            del result  # Delete result object
            
            # Force multiple garbage collection passes
            for i in range(3):
                collected = gc.collect()
                if collected == 0:
                    break
        else:
            # Update job with error
            # Even if optimization failed, store optimized_latex if available (user can still view/use it)
            error_message = result.error_message or "Optimization failed"
            
            # Store result with optimized_latex if available (even for failed jobs)
            # Also include error_details for frontend logging
            result_data = None
            if result.optimized_latex:
                # Generate filename even for failed jobs (if we have names)
                safe_first = first_name.strip().replace(" ", "_").replace("/", "_").title()
                safe_last = last_name.strip().replace(" ", "_").replace("/", "_").title()
                safe_company = company_name.strip().replace(" ", "_").replace("/", "_").title()
                filename = f"{safe_first}_{safe_last}_{safe_company}.pdf"
                
                result_data = {
                    "optimized_latex": result.optimized_latex,
                    "filename": filename,
                    "error_details": {
                        "iterations": result.iterations,
                        "optimized_latex_available": result.optimized_latex is not None,
                        "original_latex_length": len(resume_latex),
                        "optimized_latex_length": len(result.optimized_latex) if result.optimized_latex else 0,
                    }
                }
            else:
                # No LaTeX available, but still store error details
                # Provide default values for optimized_latex and filename to match frontend interface
                safe_first = first_name.strip().replace(" ", "_").replace("/", "_").title()
                safe_last = last_name.strip().replace(" ", "_").replace("/", "_").title()
                safe_company = company_name.strip().replace(" ", "_").replace("/", "_").title()
                filename = f"{safe_first}_{safe_last}_{safe_company}.pdf"
                
                result_data = {
                    "optimized_latex": "",  # Empty string when no LaTeX available
                    "filename": filename,  # Still provide filename for consistency
                    "error_details": {
                        "iterations": result.iterations,
                        "optimized_latex_available": False,
                        "original_latex_length": len(resume_latex),
                        "optimized_latex_length": 0,
                    }
                }
            
            update_job_status(
                job_id,
                "failed",
                completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                error_message=error_message,
                result=result_data,  # Store LaTeX and error details even for failed jobs
            )
            
            # Log minimal error to backend (full details will be logged in frontend)
            logger.error(f"[optimize_resume_task] Job {job_id} failed: {error_message}")
            
            # Cleanup even on failure
            try:
                del resume_latex
                del job_description
                if 'result' in locals():
                    del result
                for i in range(3):
                    gc.collect()
            except:
                pass
            
    except (TimeLimitExceeded, SoftTimeLimitExceeded) as e:
        # Handle timeout exceptions - mark job as failed
        error_message = f"Task timed out after {settings.celery_task_time_limit} seconds"
        logger.error(f"[optimize_resume_task] Job {job_id} timed out: {error_message}")
        
        # Try to get any partial result from the job
        job = get_job(job_id)
        result_data = None
        if job and job.get("result"):
            try:
                import json
                existing_result = job.get("result")
                if isinstance(existing_result, str):
                    existing_result = json.loads(existing_result)
                result_data = existing_result
            except:
                pass
        
        # If no result data, provide default structure
        if not result_data:
            result_data = {
                "optimized_latex": "",
                "filename": "resume.pdf",
                "error_details": {
                    "iterations": 0,
                    "optimized_latex_available": False,
                    "original_latex_length": len(resume_latex) if 'resume_latex' in locals() else 0,
                    "optimized_latex_length": 0,
                }
            }
        
        update_job_status(
            job_id,
            "failed",
            completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            error_message=error_message,
            result=result_data,
        )
        # Don't re-raise - timeout is a final failure, not retryable
        
    except Exception as e:
        logger.exception(f"[optimize_resume_task] Error during optimization for job {job_id}")
        
        # Update job with error
        update_job_status(
            job_id,
            "failed",
            completed_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            error_message=str(e),
        )
        
        # Re-raise to trigger Celery retry (for non-timeout exceptions)
        # Cleanup on exception
        try:
            if 'resume_latex' in locals():
                del resume_latex
            if 'job_description' in locals():
                del job_description
            if 'result' in locals():
                del result
            for i in range(3):
                gc.collect()
        except:
            pass
        
        raise
    finally:
        # Final cleanup
        pass

