"""Alembic environment configuration.

Database URL is resolved in this order:
  1. DATABASE_URL environment variable (preferred; allows DB-only migration runs)
  2. alembic.ini [alembic] sqlalchemy.url
  3. App settings (when running from full app context)

When only DATABASE_URL is set (e.g. CI or migration-only containers), placeholder
env vars are set so that importing api.database (for target_metadata) does not
require OPENAI_API_KEY or REDIS_URL.
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Allow running migrations with only DATABASE_URL set (no OpenAI/Redis required)
if not os.environ.get("OPENAI_API_KEY"):
    os.environ.setdefault("OPENAI_API_KEY", "alembic-placeholder")
if not os.environ.get("REDIS_URL"):
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

from api.database import Base
import api.db_models  # noqa: F401 — registers models with Base
from tailor_tom.config import settings

# ---------------------------------------------------------------------------
# Alembic Config and URL resolution (DB-only when DATABASE_URL is set)
# ---------------------------------------------------------------------------
config = context.config

url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
if not url:
    url = settings.database_url
if url:
    config.set_main_option("sqlalchemy.url", url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
