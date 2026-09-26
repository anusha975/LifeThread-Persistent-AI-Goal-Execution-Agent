.PHONY: help setup dev test lint format build clean verify-env ci

PYTHON ?= python
NPM ?= npm

help:
	@echo "LifeThread Monorepo Commands:"
	@echo "  make setup       - Install backend, agent, mcp-server, and frontend dependencies"
	@echo "  make dev         - Start PostgreSQL and Redis via Docker Compose, and launch services"
	@echo "  make test        - Run unit and integration tests across packages"
	@echo "  make lint        - Run linting checks across python and frontend code"
	@echo "  make format      - Auto-format codebases"
	@echo "  make build       - Build frontend and verify packaging"
	@echo "  make verify-env  - Validate environment variables against .env.example"
	@echo "  make ci          - Execute full 9-stage CI/CD pipeline locally"
	@echo "  make clean       - Remove caches, temporary files, and build outputs"

setup:
	@echo "==> Setting up environment..."
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example"; fi
	@echo "==> Installing Python packages..."
	$(PYTHON) -m pip install -e ./backend
	$(PYTHON) -m pip install -e ./agent
	$(PYTHON) -m pip install -e ./mcp-server
	@echo "==> Installing frontend dependencies..."
	cd frontend && $(NPM) install

verify-env:
	$(PYTHON) scripts/verify_env.py

dev:
	@echo "==> Starting local infrastructure with Docker Compose..."
	docker compose up -d postgres redis

test:
	@echo "==> Running pytest test suite..."
	$(PYTHON) -m pytest tests/

lint:
	@echo "==> Running Python linter (ruff)..."
	$(PYTHON) -m ruff check .
	@echo "==> Running frontend type check..."
	cd frontend && $(NPM) run typecheck

format:
	@echo "==> Formatting Python code..."
	$(PYTHON) -m ruff format .
	@echo "==> Formatting frontend code..."
	cd frontend && $(NPM) run format

build:
	@echo "==> Building frontend production bundle..."
	cd frontend && $(NPM) run build

ci:
	@echo "==> Running full 9-stage CI/CD pipeline..."
	$(PYTHON) scripts/run_ci_pipeline.py

clean:
	@echo "==> Cleaning cache and build artifacts..."
	rm -rf .pytest_cache .ruff_cache frontend/dist frontend/node_modules
	find . -type d -name "__pycache__" -exec rm -rf {} +
