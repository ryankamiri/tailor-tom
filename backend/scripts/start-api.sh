#!/bin/sh
# Production API startup: run migrations then start uvicorn.
# Fails container startup if migrations fail so worker never sees an outdated schema.
set -e
cd /app
echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete. Starting API..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
