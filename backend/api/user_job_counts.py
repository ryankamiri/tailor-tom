"""Update User daily job counters (used by API and worker).

Caller is responsible for committing the session.
"""

from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from api.db_models import User


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def increment_active_jobs(db: Session, user_id: UUID) -> None:
    """Increment active_jobs_count for the user. Caller must commit."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        user.active_jobs_count += 1


def decrement_active_jobs(db: Session, user_id: UUID) -> None:
    """Decrement active_jobs_count for the user (floor at 0). Caller must commit."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        user.active_jobs_count = max(0, user.active_jobs_count - 1)


def record_job_completed(db: Session, user_id: UUID) -> None:
    """Record one completed job for today (UTC). Resets daily count if date changed. Caller must commit."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return
    today = _today_utc()
    if user.daily_completions_date is None or user.daily_completions_date < today:
        user.daily_completions_date = today
        user.daily_completions_count = 1
    else:
        user.daily_completions_count += 1


def on_job_terminated(db: Session, user_id: str | UUID | None, status: str) -> None:
    """Call when a job reaches a terminal state (completed, failed, or cancelled).
    Decrements active_jobs_count; only for status 'completed' records daily completion.
    Caller must commit.
    """
    if not user_id:
        return
    uid = user_id if isinstance(user_id, UUID) else UUID(user_id)
    decrement_active_jobs(db, uid)
    if status == "completed":
        record_job_completed(db, uid)
