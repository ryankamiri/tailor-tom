"""add daily job count columns to users

Revision ID: a1b2c3d4e5f6
Revises: 39a738bd5a55
Create Date: 2026-01-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '39a738bd5a55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('daily_completions_date', sa.Date(), nullable=True))
    op.add_column('users', sa.Column('daily_completions_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('active_jobs_count', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'active_jobs_count')
    op.drop_column('users', 'daily_completions_count')
    op.drop_column('users', 'daily_completions_date')
