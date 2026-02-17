"""Drop max_bullet_lines columns from users and jobs.

Revision ID: a9d4f6e2b1c7
Revises: f0a1b2c3d4e5
Create Date: 2026-02-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9d4f6e2b1c7"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("jobs", "max_bullet_lines")
    op.drop_column("users", "max_bullet_lines")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("max_bullet_lines", sa.Integer(), server_default=sa.text("2"), nullable=False),
    )
    op.add_column(
        "jobs",
        sa.Column("max_bullet_lines", sa.Integer(), server_default=sa.text("2"), nullable=False),
    )
