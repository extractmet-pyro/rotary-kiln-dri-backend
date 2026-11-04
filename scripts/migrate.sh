#!/usr/bin/env bash
# Apply database migrations (PostgreSQL/TimescaleDB or SQLite) using DATABASE_URL.
set -euo pipefail
cd "$(dirname "$0")/.."
alembic upgrade head
