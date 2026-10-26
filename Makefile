# ACME Corp IPA: one-command local setup (F33).
#   make setup   install backend + frontend dependencies and seed acme.db
#   make dev     run FastAPI (:8000) and the Angular dev server (:4200) together; Ctrl+C stops both

PYTHON ?= python3
VENV   := backend/.venv
PY     := $(VENV)/bin/python

.PHONY: setup backend-setup frontend-setup seed dev backend frontend test e2e

setup: backend-setup frontend-setup seed

backend-setup:
	@test -x $(PY) || (command -v uv >/dev/null 2>&1 && uv venv --quiet $(VENV)) || $(PYTHON) -m venv $(VENV)
	@if command -v uv >/dev/null 2>&1; then \
		uv pip install --quiet --python $(PY) -e "backend[dev]"; \
	else \
		$(PY) -m pip --version >/dev/null 2>&1 || $(PY) -m ensurepip --upgrade; \
		$(PY) -m pip install --quiet -e "backend[dev]"; \
	fi

frontend-setup:
	npm ci --prefix frontend

seed:
	$(PY) -m acme.db seed

dev:
	@$(PY) -m acme.llm || [ $$? -eq 1 ]  # warns without an LLM key (servers still start); stops on an invalid provider
	@echo "Backend  http://localhost:8000/docs"
	@echo "Web app  http://localhost:4200  (Ctrl+C stops both)"
	@trap 'kill 0' INT TERM EXIT; \
	$(PY) -m uvicorn acme.api.app:create_app --factory --port 8000 & \
	npm --prefix frontend start & \
	wait

backend:
	$(PY) -m uvicorn acme.api.app:create_app --factory --port 8000

frontend:
	npm --prefix frontend start

test:
	$(PY) -m pytest backend/tests
	npm --prefix frontend run test:ci

e2e:
	cd frontend && npx playwright install chromium && npx playwright test
