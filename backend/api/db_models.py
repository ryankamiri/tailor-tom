"""SQLAlchemy ORM models — source of truth for the DB schema.

Tables:
  - users           one row per user; resume + settings denormalized
  - jobs            one row per optimization job
  - job_global_stats single-row aggregate counters (id = 1)

Auth: users table includes Google OAuth fields; jobs.user_id is NOT NULL and CASCADE.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.database import Base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# users
# ---------------------------------------------------------------------------

class User(Base):
    """One row per user.  Resume + settings are denormalized here."""

    __tablename__ = "users"

    # PK
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )

    # Google OAuth fields (populated at sign-in)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    google_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Name fields (also used for filename generation)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Denormalized resume (one resume per user)
    resume_latex: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Role
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )

    # User-level defaults / settings
    max_iterations: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    target_pages: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    max_bullet_lines: Mapped[int] = mapped_column(Integer, default=2, server_default=text("2"))

    # Daily job limit counters (UTC date; None or past date = 0 completed today)
    daily_completions_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    daily_completions_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    active_jobs_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    # Relationships
    jobs: Mapped[list["Job"]] = relationship(back_populates="user", lazy="select")

    def __repr__(self) -> str:
        return f"<User {self.email}>"


# ---------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------

class Job(Base):
    """One row per optimization job."""

    __tablename__ = "jobs"

    # PK — short random string (e.g. 16-char hex), not auto-increment
    id: Mapped[str] = mapped_column(String(32), primary_key=True)

    # FK to users — required; CASCADE so job rows are removed when user is deleted
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Job metadata
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Input data (stored so we can replay / audit)
    original_latex: Mapped[str] = mapped_column(Text, nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    target_pages: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    max_iterations: Mapped[int] = mapped_column(Integer, default=3, server_default=text("3"))
    job_description: Mapped[str] = mapped_column(Text, nullable=False)
    max_bullet_lines: Mapped[int] = mapped_column(Integer, default=2, server_default=text("2"))
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Restart tracking
    restart_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_restart_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Result columns (populated on completion)
    optimized_latex: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    optimized_latex_available: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    original_latex_length: Mapped[int | None] = mapped_column(Integer, nullable=True)
    optimized_latex_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # V3 optimizer analysis (canonical)
    optimizer_version: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=3, server_default=text("3")
    )
    analysis_json: Mapped[dict | list | None] = mapped_column(JSONB(), nullable=True)
    llm_usage_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_estimated_cost_usd: Mapped[float | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )

    # Timestamps
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    # Relationships
    user: Mapped[User] = relationship(back_populates="jobs", lazy="select")

    # Indexes (beyond the ones created by `index=True` above)
    # Composite indexes for cursor pagination (match migration b7f4c2d9e3a1)
    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_created_at", "created_at"),
        Index("ix_jobs_user_created_id_desc", "user_id", "created_at", "id"),
        Index("ix_jobs_user_status_created_id_desc", "user_id", "status", "created_at", "id"),
    )

    def __repr__(self) -> str:
        return f"<Job {self.id} [{self.status}]>"


# ---------------------------------------------------------------------------
# job_global_stats  (single row, id = 1)
# ---------------------------------------------------------------------------

class JobGlobalStats(Base):
    """Singleton aggregate counters — always id = 1. processed = completed + failed + cancelled."""

    __tablename__ = "job_global_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    completed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    failed: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    cancelled: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=text("now()"),
    )

    def __repr__(self) -> str:
        return f"<JobGlobalStats processed={self.processed} completed={self.completed} failed={self.failed} cancelled={self.cancelled}>"
