# LifeThread Production Deployment Guide

## 1. Overview

LifeThread is packaged as a set of lightweight, containerized microservices ready for deployment on Docker, Docker Compose, Kubernetes, or cloud container services (AWS ECS, Google Cloud Run, Azure Container Apps).

```
                            [ Public Internet ]
                                     |
                                     v
                        [ Nginx / Cloud Load Balancer ]
                        (SSL Termination, Port 80/443)
                                     |
                   +-----------------+-----------------+
                   |                                   |
                   v (Port 8000)                       v (Port 5173 / Static)
          [ Backend API Gateway ]             [ Frontend SPA Client ]
          (FastAPI / Uvicorn)                 (Nginx / Vite Static)
                   |
         +---------+---------+
         |                   | (Port 8001)
         v                   v
+-----------------+ +-----------------+
|  PostgreSQL 16  | |   MCP Server    |
|   + pgvector    | | (Tool Services) |
+-----------------+ +-----------------+
         |
         v
+-----------------+
|     Redis 7     |
| (Cache/Tokens)  |
+-----------------+
```

---

## 2. Docker Container Images

All images use multi-stage builds based on `python:3.12-slim` and `node:20-alpine`, running under an unprivileged non-root user (`appuser`, UID 10001) with minimal attack surfaces.

### 2.1 Backend Image (`infrastructure/docker/backend.Dockerfile`)
- Builds dependencies in a builder stage with wheels caching.
- Final stage copies only pre-built wheels and application code.
- Exposed Port: `8000`.
- Health Check: `curl -f http://localhost:8000/api/v1/health || exit 1`.

### 2.2 MCP Server Image (`infrastructure/docker/mcp.Dockerfile`)
- Houses the standalone MCP tool execution runner.
- Exposed Port: `8001`.
- Health Check: `curl -f http://localhost:8001/health || exit 1`.

### 2.3 Frontend Image (`infrastructure/docker/frontend.Dockerfile`)
- Stage 1: Builds the React/TypeScript bundle via Vite.
- Stage 2: Serves static assets via unprivileged Nginx with caching headers and Gzip compression.
- Exposed Port: `80` (or mapped to `5173`/`80`).

---

## 3. Docker Compose Stacks

The repository includes pre-configured Docker Compose stacks for different deployment modes:

### 3.1 Production Stack (`docker-compose.yml`)
Launches the full production-hardened environment:
```bash
# Start all production services in the background
docker compose up -d

# Verify container statuses
docker compose ps

# View service logs
docker compose logs -f backend
```

### 3.2 Development Stack (`docker-compose.dev.yml`)
Mounts source code volumes for live reloading:
```bash
docker compose -f docker-compose.dev.yml up -d
```

### 3.3 Ephemeral Test Stack (`docker-compose.test.yml`)
Runs the automated test suite inside isolated test containers:
```bash
docker compose -f docker-compose.test.yml up --abort-on-container-exit --exit-code-from test-runner
```

---

## 4. Environment Variables Checklist

Ensure the following variables are configured in `.env` or injected by your cloud secret manager:

| Variable | Description | Production Example |
|---|---|---|
| `ENVIRONMENT` | Deployment stage | `production` |
| `ALLOW_DEMO_DATA` | Guard for demo dataset seeding | `False` |
| `SECRET_KEY` | Cryptographic key for signing JWTs | `32+ random hex characters` |
| `DATABASE_URL` | Async PostgreSQL connection string | `postgresql+asyncpg://user:pass@host:5432/dbname` |
| `REDIS_URL` | Redis connection URL | `redis://:pass@host:6379/0` |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins | `https://app.lifethread.ai` |
| `MCP_SERVER_URL` | URL to internal MCP service | `http://mcp-server:8001` |
| `OPENAI_API_KEY` | Key for LLM and embedding generation | `sk-prod-...` |

---

## 5. CI/CD Pipeline (`.github/workflows/ci.yml`)

The repository features an automated 9-stage GitHub Actions CI/CD workflow:
1. **Lint & Format:** Runs Ruff on all Python packages.
2. **Type Check:** Runs TypeScript check (`tsc`) on frontend code.
3. **Database Validation:** Tests Alembic migration scripts against fresh PostgreSQL.
4. **Unit Tests:** Executes isolated unit tests across backend, agent, and mcp-server.
5. **Security Scan:** Runs vulnerability audit on Python and npm dependencies.
6. **E2E Integration:** Executes `test_module_44_end_to_end_lifecycle.py`.
7. **Performance Benchmark:** Verifies latency budgets and prevents regressions.
8. **Container Build:** Compiles and tests multi-stage Docker images.
9. **Artifact Publishing:** Tags and pushes production images to the container registry upon release.
