"""Celery tasks for TailorTom optimization jobs."""

import base64
import ctypes
import gc
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from billiard.exceptions import TimeLimitExceeded
from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import task_failure, worker_ready

from worker.celery_app import celery_app
from worker.discord_webhook import notify_task_failure
from api.conversion_storage import (
    CONVERSION_KEY_PREFIX,
    CONVERSION_TTL,
    get_redis_client as get_convert_redis,
)
from api.cache import invalidate_user_profile_cache
from api.storage import update_job_status, get_job, get_orphaned_processing_jobs, get_stuck_pending_jobs
from api.database import SessionLocal
from api.user_job_counts import on_job_terminated
from tailor_tom.config import settings
from tailor_tom.docx_converter import generate_latex_from_docx
from tailor_tom.llm_runtime import configure_dspy
from tailor_tom.optimizer.v3.orchestrator import optimize_resume_v3
from tailor_tom.optimizer.v3.types import V3OptimizationResult
from tailor_tom.optimizer.v3.debug_logging import debug_enabled, debug_log

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)  # Only log errors for Celery tasks


def _sync_user_job_counts(job_id: str, status: str) -> None:
    """Update User daily/active job counts after a job reaches a terminal state. No-op if no user_id.
    Invalidates user profile cache after counter update so GET /auth/me sees fresh limits."""
    if status not in ("completed", "failed", "cancelled"):
        return
    try:
        job = get_job(job_id)
        user_id = job.get("user_id") if job else None
        if not user_id:
            return
        db = SessionLocal()
        try:
            on_job_terminated(db, user_id, status)
            db.commit()
        finally:
            db.close()
        invalidate_user_profile_cache(str(user_id))
    except Exception as e:
        logger.error(f"[_sync_user_job_counts] Failed to update user counts for job {job_id}: {e}")


def _v3_result_to_db_payload(result: V3OptimizationResult) -> dict:
    """Build DB column values from V3OptimizationResult. Writes analysis_json, llm_usage_source, token/cost fields."""
    analysis_json: dict = {
        "passes_done": result.passes_done,
        "quality_passes": result.quality_passes,
        "quality_issues_summary": result.quality_issues_summary or "",
        "diagnostics": result.diagnostics or {},
    }
    if result.token_usage:
        analysis_json["token_usage"] = {
            "prompt_tokens": result.token_usage.prompt_tokens,
            "completion_tokens": result.token_usage.completion_tokens,
            "estimated_cost_usd": result.token_usage.estimated_cost_usd,
            "usage_source": result.token_usage.usage_source,
        }
    payload = {
        "analysis_json": analysis_json,
        "llm_usage_source": result.token_usage.usage_source if result.token_usage else None,
        "llm_prompt_tokens": result.token_usage.prompt_tokens if result.token_usage else None,
        "llm_completion_tokens": result.token_usage.completion_tokens if result.token_usage else None,
        "llm_estimated_cost_usd": result.token_usage.estimated_cost_usd if result.token_usage else None,
    }
    return payload


def _append_warning_json_array(existing_text: str, warning: str) -> str:
    """Append a warning to a JSON array string. Returns compact JSON. Never raises."""
    try:
        existing = json.loads(existing_text) if (existing_text or "").strip() else []
        if not isinstance(existing, list):
            existing = [existing] if existing else []
    except Exception:
        existing = []
    existing.append(warning)
    return json.dumps(existing, separators=(",", ":"))


def _filename_from_job(job: dict | None) -> str:
    """Build FirstName_LastName_CompanyName.pdf from job data. Falls back to 'resume.pdf' if job/names missing."""
    if not job:
        return "resume.pdf"
    first = (job.get("first_name") or "").strip().replace(" ", "_").replace("/", "_").title() or "Unknown"
    last = (job.get("last_name") or "").strip().replace(" ", "_").replace("/", "_").title() or "Unknown"
    company = (job.get("company_name") or "").strip().replace(" ", "_").replace("/", "_").title() or "Resume"
    return f"{first}_{last}_{company}.pdf"


def _now_utc_iso() -> str:
    """Current UTC time as ISO string with Z suffix."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _build_default_failure_result(
    job: dict | None,
    *,
    original_latex_len: int = 0,
    iterations: int = 0,
    optimized_latex_available: bool = False,
    optimized_latex_length: int = 0,
) -> dict:
    """Default result dict for failed jobs (optimize task)."""
    return {
        "optimized_latex": "",
        "filename": _filename_from_job(job),
        "error_details": {
            "iterations": iterations,
            "optimized_latex_available": optimized_latex_available,
            "original_latex_length": original_latex_len,
            "optimized_latex_length": optimized_latex_length,
        },
    }


def _process_memory_cleanup() -> None:
    """Run GC and malloc_trim to reduce worker memory footprint. Safe to call from finally."""
    for _ in range(3):
        if gc.collect() == 0:
            break
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass


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

    try:
        # Recover orphaned 'processing' jobs
        orphaned_jobs = get_orphaned_processing_jobs()

        if orphaned_jobs:
            queue_name = settings.celery_queue_name
            re_enqueued = 0
            for job_data in orphaned_jobs:
                job_id = job_data.get("job_id")
                if not job_id:
                    continue

                # Check restart count - fail after 3 attempts
                restart_count = int(job_data.get("restart_count", "0"))
                last_restart_time = job_data.get("last_restart_time", "")

                if restart_count >= 3:
                    logger.error(
                        f"[worker_ready] Job {job_id} has been restarted {restart_count} times. "
                        f"Marking as failed to prevent infinite loop."
                    )
                    update_job_status(
                        job_id,
                        "failed",
                        completed_at=_now_utc_iso(),
                        error_message=(
                            "Job failed after multiple worker restarts. "
                            "This may indicate a memory issue or job complexity exceeding system limits. "
                            "Please try again with a simpler resume or contact support."
                        ),
                        result=_build_default_failure_result(job_data),
                    )
                    _sync_user_job_counts(job_id, "failed")
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
            
                try:
                    # Increment restart counter
                    new_restart_count = restart_count + 1

                    # Re-enqueue with job_id only (worker loads job from DB)
                    optimize_resume_task.apply_async(
                        kwargs={"job_id": job_id},
                        queue=queue_name,
                        priority=5,  # lower than DOCX (0) so DOCX runs first
                    )

                    # Reset status to pending and update restart tracking in DB
                    update_job_status(
                        job_id,
                        "pending",
                        restart_count=str(new_restart_count),
                        last_restart_time=_now_utc_iso(),
                    )
                    re_enqueued += 1

                except Exception as e:
                    logger.error(f"[worker_ready] Failed to re-enqueue job {job_id}: {e}")
                    # Still reset to pending in case task is in queue
                    update_job_status(job_id, "pending")

        # Re-enqueue jobs stuck in 'pending' (task never enqueued or lost, e.g. Redis was down at submit)
        min_pending_age = 60  # 1 minute
        stuck_pending = get_stuck_pending_jobs(min_age_seconds=min_pending_age)
        if stuck_pending:
            queue_name = settings.celery_queue_name
            for job_data in stuck_pending:
                job_id = job_data.get("job_id")
                if not job_id:
                    continue
                try:
                    optimize_resume_task.apply_async(
                        kwargs={"job_id": job_id},
                        queue=queue_name,
                        priority=5,
                    )
                except Exception as e:
                    logger.error(f"[worker_ready] Failed to re-enqueue stuck pending job {job_id}: {e}")
    except Exception as e:
        # Don't let recovery errors prevent worker from starting
        logger.error(f"[worker_ready] Error during job recovery: {e}")


def _on_task_failure(self, exc, task_id, args, kwargs, einfo):
    """Callback when task fails (including timeouts and crashes).

    Task is invoked with kwargs={"job_id": ...} only.
    """
    try:
        job_id = (kwargs or {}).get("job_id") or (args[0] if args else None)
        
        if job_id:
            # Do not overwrite cancelled with failed (user-initiated cancel wins)
            job = get_job(job_id)
            if job and job.get("status") not in ("failed", "cancelled"):
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
                        existing_result = job.get("result")
                        if isinstance(existing_result, str):
                            existing_result = json.loads(existing_result)
                        result_data = existing_result
                    except:
                        pass
                
                if not result_data:
                    result_data = _build_default_failure_result(job)

                update_job_status(
                    job_id,
                    "failed",
                    completed_at=_now_utc_iso(),
                    error_message=error_message,
                    result=result_data,
                )
                _sync_user_job_counts(job_id, "failed")
    except Exception as e:
        logger.error(f"[optimize_resume_task] Error in failure callback: {e}")


def _on_task_failure_discord(
    sender=None,
    task_id=None,
    exception=None,
    args=None,
    kwargs=None,
    **_
):
    """Send Discord webhook on any task failure (optimize_resume_task, convert_docx_task)."""
    if exception is None:
        return
    task_name = getattr(sender, "name", None) or "unknown"
    exc_str = f"{type(exception).__name__}: {str(exception)}"
    job_id = (kwargs or {}).get("job_id") if kwargs else None
    conversion_id = (args[0] if args else None) or (kwargs or {}).get("conversion_id")
    if not isinstance(conversion_id, str):
        conversion_id = None
    notify_task_failure(
        task_name=task_name,
        task_id=task_id or "",
        exception=exc_str,
        job_id=job_id,
        conversion_id=conversion_id,
    )


task_failure.connect(_on_task_failure_discord)


@celery_app.task(bind=True, name="worker.tasks.optimize_resume_task", on_failure=_on_task_failure)
def optimize_resume_task(self, job_id: str):
    """Celery task to optimize a resume.

    Payload is job_id only; job data is loaded from DB inside the task.
    """
    job = None
    resume_latex = None
    job_description = None
    result = None
    db_payload = None
    current = None
    result_data = None
    job_for_filename = None
    _task_start = 0.0
    _terminal_status = None
    try:
        job = get_job(job_id)
        if not job:
            logger.error(f"[optimize_resume_task] Job {job_id} not found, skipping")
            return

        status = job.get("status")
        if status == "cancelled":
            return
        if status == "failed" and job.get("error_message") == "Job cancelled by user":
            return
        if status not in ("pending", "processing"):
            logger.error(
                f"[optimize_resume_task] Job {job_id} in terminal/non-runnable state '{status}', skipping"
            )
            return
        if status == "pending":
            # Mark running as soon as worker starts executing the task so UI/clients
            # don't continue to show pending during active optimization.
            update_job_status(job_id, "processing")
            job = get_job(job_id) or job

        resume_latex = job.get("original_latex") or ""
        job_description = job.get("job_description") or ""
        target_pages = int(job.get("target_pages") or 1)
        _max_iter_raw = job.get("max_iterations")
        try:
            max_iterations = int(_max_iter_raw) if _max_iter_raw is not None else 3
        except (TypeError, ValueError):
            if debug_enabled():
                debug_log(logger, "max_iterations_fallback", raw=_max_iter_raw, fallback=3)
            max_iterations = 3
        first_name = (job.get("first_name") or "").strip() or "User"
        last_name = (job.get("last_name") or "").strip() or "Unknown"
        company_name = (job.get("company_name") or "").strip()

        _task_start = time.monotonic()
        if debug_enabled():
            debug_log(
                logger,
                "optimize_task_start",
                job_id=job_id,
                target_pages=target_pages,
                max_iterations=max_iterations,
                company_name=company_name or "(none)",
                queue=settings.celery_queue_name,
            )
            debug_log(
                logger,
                "optimize_task_input_sizes",
                job_id=job_id,
                latex_chars=len(resume_latex),
                job_description_chars=len(job_description),
            )

        configure_dspy()

        result = optimize_resume_v3(
            resume_latex=resume_latex,
            job_description=job_description,
            target_pages=target_pages,
            max_iterations=max_iterations,
            job_id=job_id,
        )

        job_for_filename = {"first_name": first_name, "last_name": last_name, "company_name": company_name}
        filename = _filename_from_job(job_for_filename)

        db_payload = _v3_result_to_db_payload(result)

        if debug_enabled():
            tu = result.token_usage
            debug_log(
                logger,
                "optimize_task_result_summary",
                job_id=job_id,
                success=result.success,
                passes_done=result.passes_done,
                prompt_tokens=tu.prompt_tokens if tu else 0,
                completion_tokens=tu.completion_tokens if tu else 0,
                estimated_cost_usd=tu.estimated_cost_usd if tu else 0.0,
                usage_source=tu.usage_source if tu else "estimated",
                quality_passes=result.quality_passes,
                quality_issues_summary=result.quality_issues_summary or "",
            )
            if settings.optimizer_debug_emit_candidate_payload:
                debug_log(logger, "optimize_task_db_payload", job_id=job_id, payload_keys=list(db_payload.keys()))

        if result.success:
            current = get_job(job_id)
            if current and current.get("status") == "cancelled":
                return
            update_job_status(
                job_id,
                "completed",
                completed_at=_now_utc_iso(),
                result={
                    "optimized_latex": result.optimized_latex,
                    "filename": filename,
                },
                company_name=company_name,
                analysis_json=db_payload.get("analysis_json"),
                llm_usage_source=db_payload.get("llm_usage_source"),
                llm_prompt_tokens=db_payload.get("llm_prompt_tokens"),
                llm_completion_tokens=db_payload.get("llm_completion_tokens"),
                llm_estimated_cost_usd=db_payload.get("llm_estimated_cost_usd"),
            )
            _sync_user_job_counts(job_id, "completed")
            _terminal_status = "completed"
        else:
            current = get_job(job_id)
            if current and current.get("status") == "cancelled":
                return
            result_data = {
                "optimized_latex": result.optimized_latex or "",
                "filename": filename,
                "error_details": {
                    "iterations": result.passes_done,
                    "optimized_latex_available": bool(result.optimized_latex),
                    "original_latex_length": len(resume_latex),
                    "optimized_latex_length": len(result.optimized_latex or ""),
                },
            }
            update_job_status(
                job_id,
                "failed",
                completed_at=_now_utc_iso(),
                error_message=result.error_message or "Optimization failed",
                result=result_data,
                analysis_json=db_payload.get("analysis_json"),
                llm_usage_source=db_payload.get("llm_usage_source"),
                llm_prompt_tokens=db_payload.get("llm_prompt_tokens"),
                llm_completion_tokens=db_payload.get("llm_completion_tokens"),
                llm_estimated_cost_usd=db_payload.get("llm_estimated_cost_usd"),
            )
            _sync_user_job_counts(job_id, "failed")
            logger.error(f"[optimize_resume_task] Job {job_id} failed: {result.error_message}")
            _terminal_status = "failed"

    except (TimeLimitExceeded, SoftTimeLimitExceeded) as e:
        # Handle timeout exceptions - mark job as failed (unless user already cancelled)
        error_message = f"Task timed out after {settings.celery_task_time_limit} seconds"
        logger.error(f"[optimize_resume_task] Job {job_id} timed out: {error_message}")
        
        # Try to get any partial result from the job
        job = get_job(job_id)
        if job and job.get("status") == "cancelled":
            return
        result_data = None
        if job and job.get("result"):
            try:
                existing_result = job.get("result")
                if isinstance(existing_result, str):
                    existing_result = json.loads(existing_result)
                result_data = existing_result
            except:
                pass
        
        if not result_data:
            orig_len = 0
            try:
                orig_len = len(resume_latex)
            except NameError:
                pass
            result_data = _build_default_failure_result(job, original_latex_len=orig_len)
        elif result_data.get("filename") == "resume.pdf":
            result_data["filename"] = _filename_from_job(job)

        update_job_status(
            job_id,
            "failed",
            completed_at=_now_utc_iso(),
            error_message=error_message,
            result=result_data,
        )
        _sync_user_job_counts(job_id, "failed")
        _terminal_status = "failed"
        # Don't re-raise - timeout is a final failure, not retryable

    except Exception as e:
        logger.exception(f"[optimize_resume_task] Error during optimization for job {job_id}")

        job = get_job(job_id)
        if job and job.get("status") == "cancelled":
            return
        update_job_status(
            job_id,
            "failed",
            completed_at=_now_utc_iso(),
            error_message=str(e),
            result=_build_default_failure_result(job),
        )
        _sync_user_job_counts(job_id, "failed")
        _terminal_status = "failed"
        raise
    finally:
        if debug_enabled() and _task_start > 0:
            debug_log(
                logger,
                "optimize_task_end",
                job_id=job_id,
                elapsed_seconds=round(time.monotonic() - _task_start, 3),
                terminal_status=_terminal_status or "unknown",
            )
        # Clear large V3 structures before cleanup so GC can reclaim them
        if result is not None:
            try:
                if getattr(result, "pdf_bytes", None) is not None:
                    result.pdf_bytes = None
                if getattr(result, "diagnostics", None) is not None:
                    result.diagnostics = None
                if getattr(result, "optimized_latex", None) is not None:
                    result.optimized_latex = None
            except Exception:
                pass
        job = None
        resume_latex = None
        job_description = None
        result = None
        db_payload = None
        current = None
        result_data = None
        job_for_filename = None
        _process_memory_cleanup()


# ---------------------------------------------------------------------------
# DOCX Conversion Task (runs on dedicated 'docx' queue)
# ---------------------------------------------------------------------------

@celery_app.task(bind=True, name="worker.tasks.convert_docx_task", max_retries=0)
def convert_docx_task(self, conversion_id: str):
    """Process DOCX-to-LaTeX conversion on the dedicated docx queue.

    Reads structured content + target_pages from Redis, calls the LLM
    classification + deterministic renderer, and stores the result back.
    """
    data = None
    latex = None
    pdf_bytes = None
    result = None
    rc = get_convert_redis()
    key = f"{CONVERSION_KEY_PREFIX}{conversion_id}"

    try:
        raw = rc.get(key)
        if not raw:
            logger.error("[convert_docx_task] Conversion %s not found in Redis", conversion_id)
            return

        data = json.loads(raw)

        # Mark as processing
        data["status"] = "processing"
        rc.setex(key, CONVERSION_TTL, json.dumps(data))

        structured_content = data["structured_content"]
        target_pages = data.get("target_pages", 1)

        latex, pdf_bytes = generate_latex_from_docx(
            structured_content, target_pages=target_pages
        )

        compiled_pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        result = {
            "status": "completed",
            "latex": latex,
            "compiled_pdf": compiled_pdf_b64,
        }
        rc.setex(key, CONVERSION_TTL, json.dumps(result))

    except Exception as exc:
        logger.exception("[convert_docx_task] Conversion %s failed: %s", conversion_id, exc)
        try:
            error_result = {
                "status": "failed",
                "error_message": str(exc),
            }
            rc.setex(key, CONVERSION_TTL, json.dumps(error_result))
        except Exception:
            pass
    finally:
        data = None
        latex = None
        pdf_bytes = None
        result = None
        _process_memory_cleanup()
