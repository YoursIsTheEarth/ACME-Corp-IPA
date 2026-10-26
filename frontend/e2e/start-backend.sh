#!/usr/bin/env bash
# Fresh backend for the e2e run with the test-only fake model (backend/tests/fake_server.py, never a real
# LLM call): new DB and uploads under e2e/.tmp, a dummy Grok key, idle auto-pay off.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
tmp="$here/.tmp"
rm -rf "$tmp" && mkdir -p "$tmp"
export DB_PATH="$tmp/acme.db" UPLOAD_DIR="$tmp/uploads" LLM_PROVIDER=grok XAI_API_KEY=test-key PAYMENT_AUTO_IDLE=false
unset ANTHROPIC_API_KEY LLM_PROVIDER_EXTRACTION LLM_PROVIDER_VALIDATION LLM_PROVIDER_APPROVAL LLM_PROVIDER_CRITIC
py="$repo/backend/.venv/bin/python"
[ -x "$py" ] || py=python
cd "$tmp"
"$py" -m acme.db seed
exec "$py" -m uvicorn fake_server:create_app --factory --app-dir "$repo/backend/tests" --port "${BACKEND_PORT:-8100}"
