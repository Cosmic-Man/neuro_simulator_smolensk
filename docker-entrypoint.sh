#!/bin/sh
set -eu

echo "Applying database migrations..."
python -m alembic upgrade head

echo "Creating demo users if needed..."
python -m app.manage seed-demo-users

echo "Starting FastAPI..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
