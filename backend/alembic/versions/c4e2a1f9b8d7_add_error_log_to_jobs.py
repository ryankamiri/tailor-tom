"""Add error_log column to jobs table.

Revision ID: c4e2a1f9b8d7
Revises: a9d4f6e2b1c7
Create Date: 2026-03-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e2a1f9b8d7"
down_revision: Union[str, Sequence[str], None] = "a9d4f6e2b1c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("error_log", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "error_log")
