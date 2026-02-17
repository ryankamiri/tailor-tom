"""V3 analysis hard switch: add analysis_json and llm_usage_source; drop V2 analysis columns.

Revision ID: f0a1b2c3d4e5
Revises: e9f8a7b6c5d4
Create Date: 2026-01-22

One-cut hard switch. Legacy V2 analysis columns are removed.
Downgrade drops new columns and re-adds V2 columns (empty); data is not restored.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "e9f8a7b6c5d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new V3 columns first
    op.add_column(
        "jobs",
        sa.Column("analysis_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "jobs",
        sa.Column("llm_usage_source", sa.Text(), nullable=True),
    )
    # Update optimizer_version default to 3 (new rows get 3)
    op.alter_column(
        "jobs",
        "optimizer_version",
        server_default=sa.text("3"),
        existing_type=sa.SmallInteger(),
        existing_nullable=False,
    )
    # Drop V2 analysis columns
    op.drop_column("jobs", "optimization_warnings_text")
    op.drop_column("jobs", "optimization_explanation")
    op.drop_column("jobs", "coherence_warnings_text")
    op.drop_column("jobs", "unchanged_reasons_text")
    op.drop_column("jobs", "category_breakdown_after_text")
    op.drop_column("jobs", "category_breakdown_before_text")
    op.drop_column("jobs", "ats_score_delta")
    op.drop_column("jobs", "ats_score_after")
    op.drop_column("jobs", "ats_score_before")


def downgrade() -> None:
    op.add_column("jobs", sa.Column("ats_score_before", sa.Numeric(10, 4), nullable=True))
    op.add_column("jobs", sa.Column("ats_score_after", sa.Numeric(10, 4), nullable=True))
    op.add_column("jobs", sa.Column("ats_score_delta", sa.Numeric(10, 4), nullable=True))
    op.add_column("jobs", sa.Column("category_breakdown_before_text", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("category_breakdown_after_text", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("unchanged_reasons_text", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("coherence_warnings_text", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("optimization_explanation", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("optimization_warnings_text", sa.Text(), nullable=True))
    op.alter_column(
        "jobs",
        "optimizer_version",
        server_default=sa.text("2"),
        existing_type=sa.SmallInteger(),
        existing_nullable=False,
    )
    op.drop_column("jobs", "llm_usage_source")
    op.drop_column("jobs", "analysis_json")
