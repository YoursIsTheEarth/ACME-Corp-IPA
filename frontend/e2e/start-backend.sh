#!/usr/bin/env bash
# Fresh offline backend for the e2e run: new DB and uploads under e2e/.tmp, idle auto-pay off.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
tmp="$here/.tmp"
rm -rf "$tmp" && mkdir -p "$tmp"
export DB_PATH="$tmp/acme.db" UPLOAD_DIR="$tmp/uploads" LLM_PROVIDER=offline PAYMENT_AUTO_IDLE=false
py="$repo/backend/.venv/bin/python"
[ -x "$py" ] || py=python
cd "$tmp"
"$py" -m acme.db seed
exec "$py" -m uvicorn acme.api.app:create_app --factory --port "${BACKEND_PORT:-8100}"
