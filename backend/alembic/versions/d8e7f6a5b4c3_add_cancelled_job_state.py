"""add cancelled job state: job_global_stats.cancelled, backfill, jobs.status CHECK

Revision ID: d8e7f6a5b4c3
Revises: b7f4c2d9e3a1
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e7f6a5b4c3"
down_revision: Union[str, Sequence[str], None] = "b7f4c2d9e3a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add cancelled column to job_global_stats (default 0)
    op.add_column(
        "job_global_stats",
        sa.Column("cancelled", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )

    # Backfill: convert failed + "Job cancelled by user" -> cancelled
    op.execute(
        sa.text(
            "UPDATE jobs SET status = 'cancelled' "
            "WHERE status = 'failed' AND error_message = 'Job cancelled by user'"
        )
    )

    # Recompute global stats from jobs table so cancelled counts are correct
    op.execute(
        sa.text("""
            UPDATE job_global_stats SET
                completed = (SELECT COUNT(*) FROM jobs WHERE status = 'completed'),
                failed = (SELECT COUNT(*) FROM jobs WHERE status = 'failed'),
                cancelled = (SELECT COUNT(*) FROM jobs WHERE status = 'cancelled'),
                processed = (SELECT COUNT(*) FROM jobs WHERE status IN ('completed', 'failed', 'cancelled'))
            WHERE id = 1
        """)
    )

    # Add CHECK constraint on jobs.status
    op.create_check_constraint(
        "jobs_status_check",
        "jobs",
        "status IN ('pending', 'processing', 'completed', 'failed', 'cancelled')",
    )


def downgrade() -> None:
    op.drop_constraint("jobs_status_check", "jobs", type_="check")
    op.execute(
        sa.text(
            "UPDATE jobs SET status = 'failed', error_message = 'Job cancelled by user' "
            "WHERE status = 'cancelled'"
        )
    )
    op.drop_column("job_global_stats", "cancelled")
