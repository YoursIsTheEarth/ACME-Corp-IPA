#!/usr/bin/env bash
# Run the ACME Corp IPA backend (FastAPI, :8000; the frontend proxy expects this port) and frontend (Angular, :4200) together.
# Installs dependencies and seeds acme.db on first run. Ctrl+C stops both.
#
#   ./run.sh                      # uses .env; set XAI_API_KEY (Grok) or ANTHROPIC_API_KEY (Claude) to process invoices
#   LLM_PROVIDER=claude ./run.sh  # override the provider for this run
#   HOST=0.0.0.0 ./run.sh         # listen on all interfaces (e.g. inside a container)
set -euo pipefail

cd "$(dirname "$0")"

HOST="${HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-4200}"
VENV=backend/.venv
PY="$VENV/bin/python"

# Backend dependencies
if [[ ! -x "$PY" ]] || ! "$PY" -c "import acme.api" 2>/dev/null; then
  echo "Installing backend dependencies..."
  make backend-setup
fi

# Frontend dependencies
if [[ ! -d frontend/node_modules ]]; then
  echo "Installing frontend dependencies..."
  make frontend-setup
fi

# LLM key status: without a key both servers still start (the web app shows a banner), but no invoice is processed
status=0
llm_status="$("$PY" -m acme.llm 2>&1)" || status=$?
if (( status == 2 )); then
  echo "$llm_status" >&2
  exit 1
elif (( status != 0 )); then
  printf '\033[33m%s\033[0m\n' "$llm_status"
else
  echo "$llm_status"
fi

for port in 8000 "$WEB_PORT"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "Port $port is already in use (is the app already running?). Stop it first." >&2
    exit 1
  fi
done

"$PY" -m acme.db seed >/dev/null

trap 'kill 0' INT TERM EXIT

"$PY" -m uvicorn acme.api.app:create_app --factory --host "$HOST" --port 8000 &
npm --prefix frontend start -- --host "$HOST" --port "$WEB_PORT" &

echo "Backend  http://localhost:8000/docs"
echo "Web app  http://localhost:$WEB_PORT  (Ctrl+C stops both)"
wait
