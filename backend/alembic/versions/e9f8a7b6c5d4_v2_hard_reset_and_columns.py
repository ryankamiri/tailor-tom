"""V2 schema: add V2 analysis columns to jobs.

Revision ID: e9f8a7b6c5d4
Revises: d8e7f6a5b4c3
Create Date: 2026-01-22

Adds V2 explicit columns (optimizer_version, ats_score_*, category_breakdown_*,
unchanged_reasons_text, coherence_warnings_text, optimization_explanation,
optimization_warnings_text, llm_* tokens/cost). Schema-only; no data deletion.

Policy: Migrations must not perform destructive DELETE/TRUNCATE of user or job
data without an explicit, documented ops/runbook process. Pre-prod destructive
steps that were in this revision have been removed for first production launch.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9f8a7b6c5d4"
down_revision: Union[str, Sequence[str], None] = "d8e7f6a5b4c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # V2 explicit columns (no JSONB for core analysis data)
    op.add_column(
        "jobs",
        sa.Column("optimizer_version", sa.SmallInteger(), server_default=sa.text("2"), nullable=False),
    )
    op.add_column(
        "jobs",
        sa.Column("ats_score_before", sa.Numeric(precision=10, scale=4), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("ats_score_after", sa.Numeric(precision=10, scale=4), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("ats_score_delta", sa.Numeric(precision=10, scale=4), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("category_breakdown_before_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("category_breakdown_after_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("unchanged_reasons_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("coherence_warnings_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("optimization_explanation", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("optimization_warnings_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("llm_prompt_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("llm_completion_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("llm_estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "llm_estimated_cost_usd")
    op.drop_column("jobs", "llm_completion_tokens")
    op.drop_column("jobs", "llm_prompt_tokens")
    op.drop_column("jobs", "optimization_warnings_text")
    op.drop_column("jobs", "optimization_explanation")
    op.drop_column("jobs", "coherence_warnings_text")
    op.drop_column("jobs", "unchanged_reasons_text")
    op.drop_column("jobs", "category_breakdown_after_text")
    op.drop_column("jobs", "category_breakdown_before_text")
    op.drop_column("jobs", "ats_score_delta")
    op.drop_column("jobs", "ats_score_after")
    op.drop_column("jobs", "ats_score_before")
    op.drop_column("jobs", "optimizer_version")
