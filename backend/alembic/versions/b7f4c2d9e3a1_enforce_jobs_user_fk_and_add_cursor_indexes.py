"""enforce jobs.user_id non-null and add cursor pagination indexes

Revision ID: b7f4c2d9e3a1
Revises: a1b2c3d4e5f6
Create Date: 2026-02-13

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f4c2d9e3a1'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove legacy rows before enforcing non-null user ownership.
    op.execute(sa.text("DELETE FROM jobs WHERE user_id IS NULL"))

    # Replace FK to enforce cascade delete when users are removed.
    op.execute(sa.text("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_user_id_fkey"))
    op.alter_column('jobs', 'user_id', existing_type=sa.UUID(), nullable=False)
    op.create_foreign_key(
        'fk_jobs_user_id_users',
        'jobs',
        'users',
        ['user_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.create_index(
        'ix_jobs_user_created_id_desc',
        'jobs',
        ['user_id', 'created_at', 'id'],
        unique=False,
    )
    op.create_index(
        'ix_jobs_user_status_created_id_desc',
        'jobs',
        ['user_id', 'status', 'created_at', 'id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_jobs_user_status_created_id_desc', table_name='jobs')
    op.drop_index('ix_jobs_user_created_id_desc', table_name='jobs')

    op.drop_constraint('fk_jobs_user_id_users', 'jobs', type_='foreignkey')
    op.alter_column('jobs', 'user_id', existing_type=sa.UUID(), nullable=True)
    op.create_foreign_key(
        'jobs_user_id_fkey',
        'jobs',
        'users',
        ['user_id'],
        ['id'],
        ondelete='SET NULL',
    )
