"""Admin endpoints for viewing and managing saved resumes.

All routes require a valid JWT from a user with ``is_admin = True``.
Resumes are stored in the ``users`` table (``resume_latex`` column).
"""

import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.cache import (
    cache_get_or_set_dict,
    get_admin_user_costs_cache,
    set_admin_user_costs_cache,
)
from api.database import get_db
from api.db_models import User
from api.deps import CurrentUserIdentity, require_admin
from api.job_repository import (
    get_admin_user_costs,
    get_admin_user_summary,
    get_admin_users,
    get_admin_v3_health,
    list_jobs_for_admin_user_cursor,
    get_job_for_admin_user,
    fetch_job_envelope_cached,
    serialize_job_for_list,
    InvalidCursorError,
)
from api.storage import get_job_stats
from api.validation import validate_admin_utc_month

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)
router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resume_filename(user: User) -> str:
    """Generate a download-friendly filename for a user's resume."""
    first = re.sub(r"[^\w]", "", user.first_name or "Unknown").title()
    last = re.sub(r"[^\w]", "", user.last_name or "Unknown").title()
    short_id = str(user.id).replace("-", "")[:8]
    return f"{first}_{last}_{short_id}_resume"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/admin/stats")
async def get_stats(identity: CurrentUserIdentity = Depends(require_admin)):
    """Get global job statistics (admin only)."""
    try:
        return get_job_stats()
    except Exception as e:
        logger.exception("Failed to get job stats: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get job stats")


@router.get("/admin/users")
async def list_admin_users(
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
    search: str | None = Query(default=None, description="Search by name or email"),
    year: int | None = Query(default=None, description="UTC year for cost month"),
    month: int | None = Query(default=None, ge=1, le=12, description="UTC month 1-12"),
    sort: str = Query(default="email", description="Sort field: email, last_name, last_job_at, month_cost_usd, total_cost_usd, completed_count"),
    order: str = Query(default="asc", description="Sort order: asc, desc"),
    has_resume: bool | None = Query(default=None, description="Filter by has resume"),
    active_only: bool = Query(default=False, description="Only users with active_jobs_count > 0"),
    failed_only: bool = Query(default=False, description="Only users with at least one failed job"),
):
    """Get aggregated user rows for admin workspace. Paginated and filterable."""
    try:
        yr, mo = validate_admin_utc_month(year, month)
    except ValueError as e:
        logger.warning("Admin users list validation: %s", e)
        raise HTTPException(status_code=422, detail="Invalid year/month or filter parameters")
    try:
        return get_admin_users(
            db,
            page=page,
            limit=limit,
            search=search,
            year=yr,
            month=mo,
            sort=sort,
            order=order,
            has_resume=has_resume,
            active_only=active_only,
            failed_only=failed_only,
        )
    except ValueError as e:
        logger.warning("Admin users list: %s", e)
        raise HTTPException(status_code=422, detail="Invalid filter or sort parameters")
    except Exception as e:
        logger.exception("Failed to list admin users: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list users")


@router.get("/admin/users/{user_id}/summary")
async def get_user_summary(
    user_id: str,
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get one user's detailed summary for admin drawer. Includes recent jobs, quota, cost."""
    try:
        uid = UUID(user_id)
    except ValueError as e:
        logger.warning("Admin user summary invalid user_id: %s", e)
        raise HTTPException(status_code=422, detail="Invalid user_id")
    summary = get_admin_user_summary(db, uid)
    if summary is None:
        raise HTTPException(status_code=404, detail="User not found")
    return summary


@router.get("/admin/v3-health")
async def get_v3_health(
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get V3 optimizer health summary from recent jobs with analysis_json (admin only)."""
    try:
        return get_admin_v3_health(db, job_limit=500)
    except Exception as e:
        logger.exception("Failed to get V3 health: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get V3 health")


@router.get("/admin/user-costs")
async def get_user_costs(
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
    year: int | None = Query(default=None, description="UTC calendar year"),
    month: int | None = Query(default=None, ge=1, le=12, description="UTC calendar month 1-12"),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
):
    """Get per-user cost analytics: lifetime and selected UTC month. Admin only.
    Omit year/month to use current UTC month. Results are paginated and cached."""
    try:
        yr, mo = validate_admin_utc_month(year, month)
    except ValueError as e:
        logger.warning("Admin user-costs validation: %s", e)
        raise HTTPException(status_code=422, detail="Invalid year/month parameters")
    try:
        def produce() -> dict:
            return get_admin_user_costs(db, year=yr, month=mo, page=page, limit=limit)

        return cache_get_or_set_dict(
            get_admin_user_costs_cache,
            set_admin_user_costs_cache,
            produce,
            yr,
            mo,
            page,
            limit,
        )
    except ValueError as e:
        logger.warning("Admin user-costs: %s", e)
        raise HTTPException(status_code=422, detail="Invalid filter parameters")
    except Exception as e:
        logger.exception("Failed to get admin user costs: %s", e)
        raise HTTPException(status_code=500, detail="Failed to get user cost analytics")


# ---------------------------------------------------------------------------
# Resume CRUD (backed by users table)
# ---------------------------------------------------------------------------

@router.get("/admin/resumes")
async def list_resumes(
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
    page: int = Query(default=1, ge=1, description="Page number"),
    limit: int = Query(default=20, ge=1, le=100, description="Page size"),
):
    """List users that have a saved resume (admin only). Paginated."""
    base = db.query(User).filter(User.resume_latex.isnot(None))
    total_items = base.with_entities(func.count(User.id)).scalar() or 0
    total_pages = max(1, (total_items + limit - 1) // limit)
    offset = (page - 1) * limit
    users = (
        base.order_by(User.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "resumes": [
            {
                "user_id": str(u.id),
                "email": u.email,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "avatar_url": u.avatar_url,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "filename": _resume_filename(u) + ".pdf",
            }
            for u in users
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total_items": total_items,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    }


# ---------------------------------------------------------------------------
# Admin: view user's jobs (read-only, no impersonation)
# ---------------------------------------------------------------------------

def _parse_user_id(user_id: str) -> UUID:
    """Parse user_id to UUID; raise HTTPException 422 on invalid format."""
    try:
        return UUID(user_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail="Invalid user_id") from e


@router.get("/admin/users/{user_id}/jobs")
async def list_admin_user_jobs(
    user_id: str,
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: list[str] | None = Query(default=None),
    search: str | None = Query(default=None),
):
    """List jobs for a user (admin read-only). Cursor pagination; optional status filter and search (job_id, company_name)."""
    uid = _parse_user_id(user_id)
    if db.query(User).filter(User.id == uid).first() is None:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        status_filter = list(status) if status else None
        jobs, next_cursor = list_jobs_for_admin_user_cursor(
            db,
            user_id=uid,
            limit=limit,
            cursor=cursor,
            status=status_filter,
            search=search,
        )
    except InvalidCursorError:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    return {
        "items": [serialize_job_for_list(j) for j in jobs],
        "next_cursor": next_cursor,
        "user_id": user_id,
    }


@router.get("/admin/users/{user_id}/jobs/{job_id}", response_model=None)
async def get_admin_user_job_detail(
    user_id: str,
    job_id: str,
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get full job detail for admin view (same shape as user job detail plus owner_user_id). Uses shared job cache."""
    uid = _parse_user_id(user_id)
    envelope = fetch_job_envelope_cached(db, job_id, caller="admin_detail")
    if not envelope:
        raise HTTPException(status_code=404, detail="Job not found")
    if envelope.get("owner_user_id") != str(uid):
        raise HTTPException(status_code=404, detail="Job not found")
    payload = {
        "job_id": envelope["job_id"],
        "status": envelope["status"],
        "created_at": envelope["created_at"],
        "completed_at": envelope.get("completed_at"),
        "error_message": envelope.get("error_message"),
        "error_log": envelope.get("error_log"),
        "company_name": envelope.get("company_name"),
        "result": envelope.get("result"),
        "original_latex": envelope.get("original_latex"),
        "optimizer_version": envelope.get("optimizer_version"),
        "llm_prompt_tokens": envelope.get("llm_prompt_tokens"),
        "llm_completion_tokens": envelope.get("llm_completion_tokens"),
        "llm_estimated_cost_usd": envelope.get("llm_estimated_cost_usd"),
        "llm_usage_source": envelope.get("llm_usage_source"),
        "owner_user_id": envelope["owner_user_id"],
    }
    if isinstance(envelope.get("analysis_json"), dict):
        payload["analysis"] = envelope["analysis_json"]
    return payload


@router.get("/admin/users/{user_id}/jobs/{job_id}/latex")
async def get_admin_user_job_latex(
    user_id: str,
    job_id: str,
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get optimized LaTeX for a user's job (admin read-only). Same terminal-state behavior as user endpoint. Uses shared job cache."""
    uid = _parse_user_id(user_id)
    envelope = fetch_job_envelope_cached(db, job_id, caller="admin_detail")
    if not envelope:
        raise HTTPException(status_code=404, detail="Job not found")
    if envelope.get("owner_user_id") != str(uid):
        raise HTTPException(status_code=404, detail="Job not found")
    if envelope.get("status") not in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is not in a terminal state (status: {envelope.get('status')})",
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


# ---------------------------------------------------------------------------
# Resumes
# ---------------------------------------------------------------------------

@router.get("/admin/resumes/{user_id}")
async def get_resume_detail(
    user_id: str,
    identity: CurrentUserIdentity = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get full resume data including LaTeX for a specific user (admin only)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.resume_latex:
        raise HTTPException(status_code=404, detail="Resume not found")

    return {
        "user_id": str(user.id),
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "avatar_url": user.avatar_url,
        "latex": user.resume_latex,
        "filename": _resume_filename(user) + ".pdf",
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


