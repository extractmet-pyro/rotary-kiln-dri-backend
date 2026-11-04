#!/usr/bin/env bash
# Run-all: lint + compile + full pytest (unit, physics, ml, mpc, integration, e2e).
set -euo pipefail
cd "$(dirname "$0")/.."
ruff check app tests scripts || { echo "lint failed"; exit 1; }
python -m compileall -q app
python -m pytest -q "$@"
