#!/usr/bin/env bash
# Package this repository as rotary-kiln-dri-backend.zip (excludes caches and local data).
set -euo pipefail
cd "$(dirname "$0")/../.."
zip -qr rotary-kiln-dri-backend.zip rotary-kiln-dri-backend -x '*/__pycache__/*' 'rotary-kiln-dri-backend/data/*' '*.db' '*/.env' '*/.pytest_cache/*' '*/.ruff_cache/*'
echo "wrote $(pwd)/rotary-kiln-dri-backend.zip"
