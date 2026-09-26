# Infrastructure & Containerization

Docker and container orchestration setup for the LifeThread platform.

## Services

- `postgres:16-alpine`: Relational store with healthcheck (`pg_isready`).
- `redis:7-alpine`: High-performance cache and temporary state with healthcheck (`redis-cli ping`).
- `backend`: FastAPI API service container.
- `mcp-server`: Standalone MCP container.
- `frontend`: React/Vite preview/production container.

## Local Docker Compose Execution

```bash
# Start background dependencies (Postgres & Redis)
docker compose up -d postgres redis

# Start entire monorepo stack
docker compose up --build
```
