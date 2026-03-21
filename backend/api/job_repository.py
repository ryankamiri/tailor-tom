"""Database-backed job repository and cursor pagination helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import UUID

from sqlalchemy import case, Integer, tuple_, func, or_, update
from sqlalchemy.orm import Session

from api.cache import CACHE_SCHEMA_VERSION, get_job_envelope_cache, set_job_envelope_cache
from api.db_models import Job, JobGlobalStats, User

logger = logging.getLogger(__name__)

JobStatus = Literal["pending", "processing", "completed", "failed", "cancelled"]


class InvalidCursorError(ValueError):
    pass


def generate_job_id(first_name: str, last_name: str) -> str:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    combined = f"{timestamp}_{first_name}_{last_name}"
    return hashlib.md5(combined.encode()).hexdigest()[:16]


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _job_result(job: Job) -> dict[str, Any] | None:
    if not job.optimized_latex:
        return None
    return {
        "optimized_latex": job.optimized_latex,
        "filename": job.result_filename or "resume.pdf",
    }


def serialize_job_for_list(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": _dt_to_iso(job.created_at),
        "completed_at": _dt_to_iso(job.completed_at),
        "company_name": job.company_name,
        "error_message": job.error_message,
    }


def _analysis_from_job(job: Job) -> tuple[dict[str, Any] | None, bool]:
    """V3: analysis_json is canonical. Returns (analysis dict or None, parse_failed)."""
    raw = job.analysis_json
    if raw is None:
        return None, False
    if isinstance(raw, dict):
        return raw, False
    return None, True


def serialize_job_for_detail(job: Job) -> dict[str, Any]:
    payload = serialize_job_for_list(job)
    payload["result"] = _job_result(job)
    if job.status in ("completed", "failed", "cancelled"):
        payload["original_latex"] = job.original_latex or ""
    payload["optimizer_version"] = int(job.optimizer_version) if job.optimizer_version is not None else 3
    payload["llm_prompt_tokens"] = job.llm_prompt_tokens
    payload["llm_completion_tokens"] = job.llm_completion_tokens
    payload["llm_estimated_cost_usd"] = float(job.llm_estimated_cost_usd) if job.llm_estimated_cost_usd is not None else None
    payload["llm_usage_source"] = job.llm_usage_source
    # analysis / analysis_parse_failed omitted: not shown to users; admin uses DB/aggregates
    return payload


def build_job_envelope(job: Job) -> dict[str, Any]:
    """Build canonical job envelope for cache (worker + API). Includes cache_schema_version and cached_at."""
    detail = serialize_job_for_detail(job)
    envelope = dict(detail)
    envelope["job_id"] = job.id
    envelope["owner_user_id"] = str(job.user_id)
    envelope["user_id"] = str(job.user_id)
    envelope["job_description"] = job.job_description
    envelope["first_name"] = job.first_name
    envelope["last_name"] = job.last_name
    envelope["original_latex"] = job.original_latex or ""
    envelope["target_pages"] = int(job.target_pages or 1)
    envelope["max_iterations"] = int(job.max_iterations or 3)
    envelope["restart_count"] = str(job.restart_count or 0)
    envelope["last_restart_time"] = (
        job.last_restart_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if job.last_restart_time
        else ""
    )
    envelope["analysis_json"] = job.analysis_json
    envelope["error_log"] = job.error_log
    envelope["cache_schema_version"] = CACHE_SCHEMA_VERSION
    envelope["cached_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if envelope.get("result") is None and job.optimized_latex:
        envelope["result"] = {
            "optimized_latex": job.optimized_latex,
            "filename": job.result_filename or "resume.pdf",
        }
    return envelope


def fetch_job_envelope_cached(
    db: Session,
    job_id: str,
    caller: str = "unknown",
) -> Optional[dict[str, Any]]:
    """Cache-aside: return canonical job envelope from cache or DB. Fail-open to DB on Redis errors."""
    cached = get_job_envelope_cache(job_id)
    if cached is not None:
        logger.debug("job_cache_hit job_id=%s caller=%s cache_schema_version=%s", job_id, caller, cached.get("cache_schema_version"))
        return cached
    job = get_job_by_id(db, job_id)
    if not job:
        return None
    envelope = build_job_envelope(job)
    set_job_envelope_cache(job_id, envelope)
    logger.debug("job_cache_miss job_id=%s caller=%s cache_schema_version=%s", job_id, caller, envelope.get("cache_schema_version"))
    return envelope


def encode_cursor(created_at: datetime, job_id: str) -> str:
    payload = {
        "created_at": created_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "id": job_id,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode())
        payload = json.loads(raw)
        created_at_raw = payload["created_at"]
        job_id = payload["id"]
        created_at = datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        return created_at, job_id
    except Exception as exc:
        raise InvalidCursorError("Invalid cursor") from exc


def get_or_create_global_stats(db: Session) -> JobGlobalStats:
    row = db.query(JobGlobalStats).filter(JobGlobalStats.id == 1).first()
    if row is None:
        row = JobGlobalStats(id=1, processed=0, completed=0, failed=0, cancelled=0)
        db.add(row)
        db.flush()
    return row


def create_job(
    db: Session,
    *,
    job_id: str,
    user_id: UUID,
    original_latex: str,
    company_name: str | None,
    target_pages: int,
    max_iterations: int,
    job_description: str,
    first_name: str,
    last_name: str,
) -> Job:
    job = Job(
        id=job_id,
        user_id=user_id,
        status="pending",
        original_latex=original_latex,
        company_name=company_name,
        target_pages=target_pages,
        max_iterations=max_iterations,
        job_description=job_description,
        first_name=first_name,
        last_name=last_name,
    )
    db.add(job)
    db.flush()
    return job


def get_job_for_user(db: Session, job_id: str, user_id: UUID) -> Job | None:
    return (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == user_id)
        .first()
    )


def get_job_by_id(db: Session, job_id: str) -> Job | None:
    return db.query(Job).filter(Job.id == job_id).first()


def get_job_status_by_id(db: Session, job_id: str) -> str | None:
    """Lightweight status-only fetch for cancellation checks. Returns status string or None."""
    return db.query(Job.status).filter(Job.id == job_id).limit(1).scalar()


def list_jobs_for_user_cursor(
    db: Session,
    *,
    user_id: UUID,
    limit: int,
    cursor: str | None,
    status: JobStatus | list[JobStatus] | None,
) -> tuple[list[Job], str | None]:
    query = db.query(Job).filter(Job.user_id == user_id)
    if status is not None:
        if isinstance(status, list):
            if status:
                query = query.filter(Job.status.in_(status))
        else:
            query = query.filter(Job.status == status)

    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        query = query.filter(
            tuple_(Job.created_at, Job.id) < tuple_(cursor_created_at, cursor_id)
        )

    rows = (
        query
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit + 1)
        .all()
    )

    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[:limit]

    return rows, next_cursor


def list_jobs_for_admin_user_cursor(
    db: Session,
    *,
    user_id: UUID,
    limit: int,
    cursor: str | None,
    status: JobStatus | list[JobStatus] | None = None,
    search: str | None = None,
) -> tuple[list[Job], str | None]:
    """Admin: list jobs for a user with optional status filter and search (job_id, company_name).
    Same cursor model and ordering as list_jobs_for_user_cursor."""
    query = db.query(Job).filter(Job.user_id == user_id)
    if status is not None:
        if isinstance(status, list):
            if status:
                query = query.filter(Job.status.in_(status))
        else:
            query = query.filter(Job.status == status)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(Job.id.ilike(term), (Job.company_name or "").ilike(term))
        )
    if cursor:
        cursor_created_at, cursor_id = decode_cursor(cursor)
        query = query.filter(
            tuple_(Job.created_at, Job.id) < tuple_(cursor_created_at, cursor_id)
        )
    rows = (
        query
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(limit + 1)
        .all()
    )
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
        rows = rows[:limit]
    return rows, next_cursor


def get_job_for_admin_user(db: Session, job_id: str, user_id: UUID) -> Job | None:
    """Admin: strict user-scoped fetch for one job. Returns None if job missing or wrong user."""
    return (
        db.query(Job)
        .filter(Job.id == job_id, Job.user_id == user_id)
        .first()
    )


def get_job_error_log(db: Session, job_id: str) -> str | None:
    """Return the error_log text for a job, or None if not set."""
    row = db.query(Job.error_log).filter(Job.id == job_id).first()
    return row.error_log if row else None


def get_job_by_id_for_admin(db: Session, job_id: str) -> Job | None:
    """Admin: fetch a job by ID with no user restriction."""
    return db.query(Job).filter(Job.id == job_id).first()


def list_processing_jobs_for_recovery(db: Session) -> list[Job]:
    return db.query(Job).filter(Job.status == "processing").all()


def list_stuck_pending_jobs_for_recovery(
    db: Session, *, min_age_seconds: int = 120
) -> list[Job]:
    """Jobs still pending after min_age_seconds (task likely lost, e.g. Redis was down)."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=min_age_seconds)
    return db.query(Job).filter(Job.status == "pending", Job.created_at < cutoff).all()


def update_job_status(
    db: Session,
    *,
    job: Job,
    status: JobStatus,
    completed_at: datetime | None = None,
    error_message: str | None = None,
    company_name: str | None = None,
    optimized_latex: str | None = None,
    result_filename: str | None = None,
    original_latex_length: int | None = None,
    optimized_latex_length: int | None = None,
    restart_count: int | None = None,
    last_restart_time: datetime | None = None,
    analysis_json: dict | list | None = None,
    llm_usage_source: str | None = None,
    llm_prompt_tokens: int | None = None,
    llm_completion_tokens: int | None = None,
    llm_estimated_cost_usd: float | None = None,
) -> None:
    previous_status = job.status

    job.status = status
    if completed_at is not None:
        job.completed_at = completed_at
    if error_message is not None:
        job.error_message = error_message
    if company_name is not None:
        job.company_name = company_name
    if optimized_latex is not None:
        job.optimized_latex = optimized_latex
        job.optimized_latex_available = len(optimized_latex) > 0
    if result_filename is not None:
        job.result_filename = result_filename
    if original_latex_length is not None:
        job.original_latex_length = original_latex_length
    if optimized_latex_length is not None:
        job.optimized_latex_length = optimized_latex_length
    if restart_count is not None:
        job.restart_count = restart_count
    if last_restart_time is not None:
        job.last_restart_time = last_restart_time
    if analysis_json is not None:
        job.analysis_json = analysis_json
    if llm_usage_source is not None:
        job.llm_usage_source = llm_usage_source
    if llm_prompt_tokens is not None:
        job.llm_prompt_tokens = llm_prompt_tokens
    if llm_completion_tokens is not None:
        job.llm_completion_tokens = llm_completion_tokens
    if llm_estimated_cost_usd is not None:
        job.llm_estimated_cost_usd = llm_estimated_cost_usd

    if previous_status != status and status in ("completed", "failed", "cancelled"):
        stats = get_or_create_global_stats(db)
        stats.processed += 1
        if status == "completed":
            stats.completed += 1
        elif status == "failed":
            stats.failed += 1
        else:
            stats.cancelled += 1


def save_job_error_log(db: Session, job_id: str, log_text: str) -> None:
    """Persist captured error log for a failed job (200 KB cap). Call before db.commit()."""
    db.execute(
        update(Job).where(Job.id == job_id).values(error_log=log_text[:200_000])
    )


def get_global_stats(db: Session) -> dict[str, int]:
    row = get_or_create_global_stats(db)
    return {
        "processed": int(row.processed),
        "completed": int(row.completed),
        "failed": int(row.failed),
        "cancelled": int(row.cancelled),
    }


def get_admin_user_summary(db: Session, user_id: UUID) -> dict[str, Any] | None:
    """Admin: one user's detailed summary for drawer view. Returns None if user not found."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    now = datetime.now(timezone.utc)
    today_utc = now.date()
    daily_used = (
        int(user.daily_completions_count or 0)
        if user.daily_completions_date and user.daily_completions_date == today_utc
        else 0
    )
    job_stats = (
        db.query(
            func.sum(case((Job.status == "completed", 1), else_=0)).label("completed_count"),
            func.sum(case((Job.status == "failed", 1), else_=0)).label("failed_count"),
            func.max(Job.completed_at).label("last_job_at"),
        )
        .filter(Job.user_id == user_id)
        .filter(Job.status.in_(["completed", "failed", "cancelled"]))
        .first()
    )
    cost_row = (
        db.query(func.coalesce(func.sum(Job.llm_estimated_cost_usd), 0).label("total_cost_usd"))
        .filter(Job.user_id == user_id)
        .filter(Job.llm_estimated_cost_usd.isnot(None))
        .first()
    )
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        month_end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    month_cost_row = (
        db.query(func.coalesce(func.sum(Job.llm_estimated_cost_usd), 0).label("month_cost_usd"))
        .filter(Job.user_id == user_id)
        .filter(Job.llm_estimated_cost_usd.isnot(None))
        .filter(Job.completed_at >= month_start)
        .filter(Job.completed_at < month_end)
        .first()
    )
    recent_jobs = (
        db.query(Job)
        .filter(Job.user_id == user_id)
        .order_by(Job.created_at.desc())
        .limit(10)
        .all()
    )
    return {
        "user_id": str(user.id),
        "email": user.email or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "is_admin": bool(user.is_admin),
        "has_resume": user.resume_latex is not None,
        "profile": {
            "email": user.email or "",
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "avatar_url": user.avatar_url,
        },
        "quota": {
            "daily_quota_used": daily_used,
            "active_jobs_count": int(user.active_jobs_count or 0),
        },
        "job_summary": {
            "completed_count": int(job_stats.completed_count or 0),
            "failed_count": int(job_stats.failed_count or 0),
            "last_job_at": _dt_to_iso(job_stats.last_job_at) if job_stats and job_stats.last_job_at else None,
        },
        "cost_summary": {
            "month_cost_usd": round(float(month_cost_row.month_cost_usd or 0), 6),
            "total_cost_usd": round(float(cost_row.total_cost_usd or 0), 6),
            "month": {"year": now.year, "month": now.month},
        },
        "recent_jobs": [
            {
                "job_id": j.id,
                "status": j.status,
                "created_at": _dt_to_iso(j.created_at),
                "completed_at": _dt_to_iso(j.completed_at) if j.completed_at else None,
                "company_name": j.company_name,
            }
            for j in recent_jobs
        ],
        "resume_metadata": {
            "has_resume": user.resume_latex is not None,
            "filename": None,  # frontend can derive from first_name, last_name
        },
    }


# Pass1 reason classification: error / warning / neutral (apply_no_effect is neutral).
PASS1_ERROR_REASONS = frozenset({
    "too_long_words", "too_long_chars", "line_count_mismatch", "compile_failed",
    "anchored_snippet_not_found", "snippet_not_found", "invalid_payload",
})
PASS1_WARNING_REASONS = frozenset({
    "too_short_words", "too_short_percent",
})
PASS1_NEUTRAL_REASONS = frozenset({"apply_no_effect"})


def get_admin_v3_health(db: Session, job_limit: int = 500) -> dict[str, Any]:
    """Aggregate V3 analysis from jobs with analysis_json. For admin observability.
    Adds pass1_error_reasons, pass1_warning_reasons, pass1_neutral_reasons, apply_no_effect_count, apply_no_effect_rate."""
    jobs = (
        db.query(Job)
        .filter(Job.analysis_json.isnot(None))
        .order_by(Job.completed_at.desc())
        .limit(job_limit)
        .all()
    )
    completed = 0
    failed = 0
    passes_done_list: list[int] = []
    pass1_merged: dict[str, int] = {}
    pass2_merged: dict[str, int] = {}
    chooser_changed_count = 0
    total_prompt = 0
    total_completion = 0
    total_cost = 0.0
    usage_source_actual = 0
    usage_source_mixed = 0
    usage_source_estimated = 0
    mapping_integrity_fail_count = 0
    total_dropped_for_mapping = 0
    total_matched_for_mapping_rate = 0  # denominator: stage0_matched_items or k

    for job in jobs:
        if job.status == "completed":
            completed += 1
        elif job.status == "failed":
            failed += 1
        raw = job.analysis_json
        if not isinstance(raw, dict):
            continue
        d = raw.get("diagnostics") or {}
        passes_done_list.append(raw.get("passes_done", 0))
        for k, v in (d.get("pass1_reason_histogram") or {}).items():
            if isinstance(v, int):
                pass1_merged[k] = pass1_merged.get(k, 0) + v
        for k, v in (d.get("pass2_reason_histogram") or {}).items():
            if isinstance(v, int):
                pass2_merged[k] = pass2_merged.get(k, 0) + v
        chosen = d.get("chooser_selected")
        if isinstance(chosen, dict):
            chooser_changed_count += len(chosen)
        if d.get("mapping_integrity_passed") is False:
            mapping_integrity_fail_count += 1
        total_dropped_for_mapping += int(d.get("dropped_for_mapping_count") or 0)
        denom = d.get("stage0_matched_items") or d.get("k") or 0
        total_matched_for_mapping_rate += int(denom)
        tu = raw.get("token_usage") or {}
        if isinstance(tu, dict):
            total_prompt += int(tu.get("prompt_tokens") or 0)
            total_completion += int(tu.get("completion_tokens") or 0)
            total_cost += float(tu.get("estimated_cost_usd") or 0)
            src = (tu.get("usage_source") or "").lower()
            if src == "actual":
                usage_source_actual += 1
            elif src == "mixed":
                usage_source_mixed += 1
            else:
                usage_source_estimated += 1

    top_pass1 = sorted(pass1_merged.items(), key=lambda x: -x[1])[:10]
    top_pass2 = sorted(pass2_merged.items(), key=lambda x: -x[1])[:10]
    avg_passes = sum(passes_done_list) / len(passes_done_list) if passes_done_list else 0

    pass1_error: dict[str, int] = {}
    pass1_warning: dict[str, int] = {}
    pass1_neutral: dict[str, int] = {}
    for k, v in pass1_merged.items():
        if k in PASS1_NEUTRAL_REASONS:
            pass1_neutral[k] = v
        elif k in PASS1_ERROR_REASONS:
            pass1_error[k] = v
        elif k in PASS1_WARNING_REASONS:
            pass1_warning[k] = v
        else:
            pass1_error[k] = v  # unknown -> treat as error for safety
    apply_no_effect_count = pass1_merged.get("apply_no_effect", 0)
    pass1_total = sum(pass1_merged.values())
    apply_no_effect_rate = (apply_no_effect_count / pass1_total) if pass1_total else 0.0

    return {
        "v3_jobs_completed": completed,
        "v3_jobs_failed": failed,
        "v3_jobs_sampled": len(jobs),
        "avg_passes_done": round(avg_passes, 2),
        "top_pass1_reasons": dict(top_pass1),
        "top_pass2_reasons": dict(top_pass2),
        "chooser_selections_total": chooser_changed_count,
        "token_prompt_total": total_prompt,
        "token_completion_total": total_completion,
        "cost_usd_total": round(total_cost, 6),
        "usage_source_actual_count": usage_source_actual,
        "usage_source_mixed_count": usage_source_mixed,
        "usage_source_estimated_count": usage_source_estimated,
        "pass1_error_reasons": pass1_error,
        "pass1_warning_reasons": pass1_warning,
        "pass1_neutral_reasons": pass1_neutral,
        "apply_no_effect_count": apply_no_effect_count,
        "apply_no_effect_rate": round(apply_no_effect_rate, 4),
        "mapping_drop_rate": round(
            total_dropped_for_mapping / total_matched_for_mapping_rate, 4
        ) if total_matched_for_mapping_rate else 0.0,
        "mapping_integrity_fail_count": mapping_integrity_fail_count,
    }


def get_admin_user_costs(
    db: Session,
    *,
    year: int | None = None,
    month: int | None = None,
    page: int = 1,
    limit: int = 20,
) -> dict[str, Any]:
    """Admin: per-user cost aggregation with pagination. Cost basis: jobs with llm_estimated_cost_usd > 0.
    Month is UTC calendar month. Sort in SQL: month_cost_usd DESC, total_cost_usd DESC, user_id ASC."""
    now = datetime.now(timezone.utc)
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    if not (1 <= month <= 12):
        raise ValueError("month must be 1..12")
    if page < 1:
        raise ValueError("page must be >= 1")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be 1..100")
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    cost_filter = Job.llm_estimated_cost_usd.isnot(None) & (Job.llm_estimated_cost_usd > 0)

    lifetime_subq = (
        db.query(
            Job.user_id,
            func.sum(Job.llm_estimated_cost_usd).label("total_cost_usd"),
            func.count(Job.id).label("job_count"),
            func.max(Job.completed_at).label("last_cost_job_at"),
        )
        .filter(cost_filter)
        .group_by(Job.user_id)
    ).subquery()

    month_subq = (
        db.query(
            Job.user_id,
            func.sum(Job.llm_estimated_cost_usd).label("month_cost_usd"),
            func.count(Job.id).label("job_count_month"),
        )
        .filter(cost_filter)
        .filter(Job.completed_at >= month_start)
        .filter(Job.completed_at < month_end)
        .group_by(Job.user_id)
    ).subquery()

    # Combined per-user aggregates (coalesce month to 0 for users with no cost in month)
    combined = (
        db.query(
            lifetime_subq.c.user_id,
            lifetime_subq.c.total_cost_usd,
            lifetime_subq.c.job_count,
            lifetime_subq.c.last_cost_job_at,
            func.coalesce(month_subq.c.month_cost_usd, 0).label("month_cost_usd"),
            func.coalesce(month_subq.c.job_count_month, 0).label("job_count_month"),
        )
        .select_from(lifetime_subq)
        .outerjoin(month_subq, lifetime_subq.c.user_id == month_subq.c.user_id)
    ).subquery()

    total_items = db.query(func.count(combined.c.user_id)).scalar() or 0
    lifetime_total = float(db.query(func.sum(combined.c.total_cost_usd)).scalar() or 0)
    month_total = float(db.query(func.sum(combined.c.month_cost_usd)).scalar() or 0)

    total_pages = max(1, (total_items + limit - 1) // limit)
    offset = (page - 1) * limit

    rows = (
        db.query(
            User.id,
            User.email,
            User.first_name,
            User.last_name,
            combined.c.total_cost_usd,
            combined.c.job_count,
            combined.c.last_cost_job_at,
            combined.c.month_cost_usd,
            combined.c.job_count_month,
        )
        .join(combined, User.id == combined.c.user_id)
        .order_by(
            combined.c.month_cost_usd.desc(),
            combined.c.total_cost_usd.desc(),
            User.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    users_list = [
        {
            "user_id": str(r.id),
            "email": r.email or "",
            "first_name": r.first_name or "",
            "last_name": r.last_name or "",
            "total_cost_usd": round(float(r.total_cost_usd or 0), 6),
            "month_cost_usd": round(float(r.month_cost_usd or 0), 6),
            "job_count_with_cost_lifetime": int(r.job_count or 0),
            "job_count_with_cost_month": int(r.job_count_month or 0),
            "last_cost_job_at": _dt_to_iso(r.last_cost_job_at) if r.last_cost_job_at else None,
        }
        for r in rows
    ]

    return {
        "month": {
            "year": year,
            "month": month,
            "utc_start": month_start.isoformat().replace("+00:00", "Z"),
            "utc_end_exclusive": month_end.isoformat().replace("+00:00", "Z"),
        },
        "summary": {
            "lifetime_total_cost_usd": round(lifetime_total, 6),
            "month_total_cost_usd": round(month_total, 6),
            "users_with_cost_count": total_items,
        },
        "pagination": {
            "page": page,
            "limit": limit,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
        "users": users_list,
    }


def get_admin_users(
    db: Session,
    *,
    page: int = 1,
    limit: int = 20,
    search: str | None = None,
    year: int | None = None,
    month: int | None = None,
    sort: str = "email",
    order: str = "asc",
    has_resume: bool | None = None,
    active_only: bool = False,
    failed_only: bool = False,
) -> dict[str, Any]:
    """Admin: aggregated user rows with identity, quota, job stats, cost stats. Server-driven pagination and sort."""
    now = datetime.now(timezone.utc)
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    if not (1 <= month <= 12):
        raise ValueError("month must be 1..12")
    if page < 1 or limit < 1 or limit > 100:
        raise ValueError("page >= 1 and limit 1..100")
    month_start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

    cost_filter = Job.llm_estimated_cost_usd.isnot(None) & (Job.llm_estimated_cost_usd > 0)
    lifetime_subq = (
        db.query(
            Job.user_id,
            func.sum(Job.llm_estimated_cost_usd).label("total_cost_usd"),
            func.count(Job.id).label("job_count"),
        )
        .filter(cost_filter)
        .group_by(Job.user_id)
    ).subquery()
    month_subq = (
        db.query(
            Job.user_id,
            func.sum(Job.llm_estimated_cost_usd).label("month_cost_usd"),
        )
        .filter(cost_filter)
        .filter(Job.completed_at >= month_start)
        .filter(Job.completed_at < month_end)
        .group_by(Job.user_id)
    ).subquery()

    job_stats_subq = (
        db.query(
            Job.user_id,
            func.sum(case((Job.status == "completed", 1), else_=0)).label("completed_count"),
            func.sum(case((Job.status == "failed", 1), else_=0)).label("failed_count"),
            func.max(Job.completed_at).label("last_job_at"),
        )
        .filter(Job.status.in_(["completed", "failed", "cancelled"]))
        .group_by(Job.user_id)
    ).subquery()

    base = (
        db.query(
            User,
            func.coalesce(job_stats_subq.c.completed_count, 0).label("completed_count"),
            func.coalesce(job_stats_subq.c.failed_count, 0).label("failed_count"),
            job_stats_subq.c.last_job_at,
            func.coalesce(lifetime_subq.c.total_cost_usd, 0).label("total_cost_usd"),
            func.coalesce(month_subq.c.month_cost_usd, 0).label("month_cost_usd"),
        )
        .select_from(User)
        .outerjoin(job_stats_subq, User.id == job_stats_subq.c.user_id)
        .outerjoin(lifetime_subq, User.id == lifetime_subq.c.user_id)
        .outerjoin(month_subq, User.id == month_subq.c.user_id)
    )
    if has_resume is True:
        base = base.filter(User.resume_latex.isnot(None))
    elif has_resume is False:
        base = base.filter(User.resume_latex.is_(None))
    if active_only:
        base = base.filter(User.active_jobs_count > 0)
    if failed_only:
        base = base.filter(job_stats_subq.c.failed_count > 0)
    if search and search.strip():
        q = f"%{search.strip()}%"
        base = base.filter(
            or_(
                User.email.ilike(q),
                User.first_name.ilike(q),
                User.last_name.ilike(q),
            )
        )

    total_items = base.count()
    total_pages = max(1, (total_items + limit - 1) // limit)
    offset = (page - 1) * limit

    sort_column = None
    if sort == "email":
        sort_column = User.email
    elif sort == "last_name":
        sort_column = User.last_name
    elif sort == "last_job_at":
        sort_column = job_stats_subq.c.last_job_at
    elif sort == "month_cost_usd":
        sort_column = month_subq.c.month_cost_usd
    elif sort == "total_cost_usd":
        sort_column = lifetime_subq.c.total_cost_usd
    elif sort == "completed_count":
        sort_column = job_stats_subq.c.completed_count
    else:
        sort_column = User.email
    if order and order.lower() == "desc":
        base = base.order_by(sort_column.desc().nullslast(), User.id.asc())
    else:
        base = base.order_by(sort_column.asc().nullsfirst(), User.id.asc())

    rows = base.offset(offset).limit(limit).all()
    today_utc = now.date()
    users_list: list[dict[str, Any]] = []
    for row in rows:
        u = row[0]
        completed_count = int(row[1] or 0)
        failed_count = int(row[2] or 0)
        last_job_at = row[3]
        total_cost_usd = float(row[4] or 0)
        month_cost_usd = float(row[5] or 0)
        daily_used = (
            int(u.daily_completions_count or 0)
            if u.daily_completions_date and u.daily_completions_date == today_utc
            else 0
        )
        users_list.append({
            "user_id": str(u.id),
            "email": u.email or "",
            "first_name": u.first_name or "",
            "last_name": u.last_name or "",
            "is_admin": bool(u.is_admin),
            "has_resume": u.resume_latex is not None,
            "active_jobs_count": int(u.active_jobs_count or 0),
            "daily_quota_used": daily_used,
            "month_cost_usd": round(month_cost_usd, 6),
            "total_cost_usd": round(total_cost_usd, 6),
            "completed_count": completed_count,
            "failed_count": failed_count,
            "last_job_at": _dt_to_iso(last_job_at) if last_job_at else None,
        })

    return {
        "month": {"year": year, "month": month},
        "pagination": {
            "page": page,
            "limit": limit,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
        "users": users_list,
    }
