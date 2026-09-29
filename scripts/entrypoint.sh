#!/bin/sh
set -eu

echo "Waiting for PostgreSQL..."
python scripts/wait_for_postgres.py

echo "Initialising database..."
python -c "import asyncio; from database.db import init_db; asyncio.run(init_db())"
export KVS_DB_INITIALIZED=1

echo "Starting application..."
exec python main.py
