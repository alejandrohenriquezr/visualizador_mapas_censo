#!/bin/sh
set -eu
echo "[db] aplicando migraciones..."
python /app/backend/db_migrate.py
workers="${BACKEND_WORKERS:-2}"
echo "[backend] iniciando uvicorn con ${workers} workers"
exec python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers "${workers}" --proxy-headers
