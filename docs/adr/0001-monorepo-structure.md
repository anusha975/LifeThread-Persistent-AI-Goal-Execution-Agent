# ADR 0001: Monorepo Repository Structure

## Status
Accepted

## Context
LifeThread requires coordinated development across an asynchronous API, a persistent AI agent orchestrator, an MCP tool server, a modern web interface, database migration scripts, and deployment infrastructure. Managing these in separate repositories would create synchronization bottlenecks, divergent typing contracts, and release friction.

## Decision
We organize the project as a single monorepo with explicit package directories:
- `backend/`: FastAPI API service.
- `frontend/`: React + TypeScript + Vite + Tailwind CSS.
- `agent/`: Independent Python package for orchestrator domain logic.
- `mcp-server/`: Independent Python package for MCP service.
- `database/`: Centralized Alembic migration and schema environment.
- `infrastructure/`: Container definitions and orchestration configs.
- `docs/`: Centralized architectural documentation and ADRs.
- `tests/`: End-to-end and cross-package test suites.

## Consequences
- Single commit history and atomic PRs across frontend, backend, agent, and MCP.
- Shared CI/CD and linting workflows (`Makefile`, `ruff`, `pyproject.toml`).
- Strict packaging guidelines must be enforced so packages do not form circular dependencies.
