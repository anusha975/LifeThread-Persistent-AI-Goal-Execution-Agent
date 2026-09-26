# LifeThread: Autonomous Persistent AI Goal-Execution Platform

> **LifeThread** is a production-grade, autonomous AI platform designed to execute complex, long-running human and organizational goals over days, weeks, or months. Given a high-level objective, LifeThread autonomously understands intent, decomposes work into a dependency graph of actionable tasks, schedules time slots, dispatches sandboxed tools via the Model Context Protocol (MCP), continuously evaluates progress, remembers historical context using vector search, and dynamically replans when circumstances change.

---

## Table of Contents

- [1. Product Overview](#1-product-overview)
- [2. System Architecture](#2-system-architecture)
- [3. Project Setup](#3-project-setup)
- [4. Environment Variables](#4-environment-variables)
- [5. Local Development](#5-local-development)
- [6. Testing Strategy](#6-testing-strategy)
- [7. API Documentation](#7-api-documentation)
- [8. Model Context Protocol (MCP) Setup](#8-model-context-protocol-mcp-setup)
- [9. Production Deployment](#9-production-deployment)
- [10. Troubleshooting & Common Issues](#10-troubleshooting--common-issues)
- [11. Technical Documentation Index](#11-technical-documentation-index)

---

## 1. Product Overview

Traditional conversational AI agents operate within ephemeral chat sessions where context evaporates when a tab closes. LifeThread treats a **Goal** as a persistent, living entity:

- **Goal Understanding:** Parses natural language intent into measurable objectives, success criteria, and strict constraints.
- **Hierarchical Decomposition:** Breaks goals into milestones and atomic tasks with estimated durations, arranged as a Directed Acyclic Graph (DAG) with explicit dependency edges (`BLOCKS`).
- **Autonomous Deterministic Planning:** Generates feasible calendar allocations matching the user's daily working capacity (e.g. 90 min/day) and computes quantitative deadline risk scores.
- **Dynamic Replanning Engine:** Automatically recalculates critical paths when deadlines compress, tasks fail, dependencies become blocked, or user weaknesses are discovered.
- **Persistent Semantic Memory:** Stores episodic execution outcomes, semantic concepts, goal invariants, and user preferences in PostgreSQL using `pgvector` for hybrid cosine similarity and recency-weighted RAG retrieval.
- **Model Context Protocol (MCP):** Connects the agent to sandboxed filesystem tools, web search, Python execution environments, calendar managers, and database diagnostic probes.
- **Comprehensive Observability:** Exposes 10 execution trace stages with automated Chain-of-Thought (CoT) sanitization to keep internal reasoning and secrets private.

---

## 2. System Architecture

LifeThread adheres to **Clean Architecture** and **Dependency Inversion** principles. Each subsystem is encapsulated within dedicated directory boundaries:

```
[ Frontend Client: React 18 + Vite + Tailwind CSS + Radix UI ]
                       │  (REST JSON / Server-Sent Events)
                       ▼
[ Backend API Gateway: FastAPI + Pydantic v2 + SQLAlchemy 2.0 Async ]
                       │  (Inversion of Control / Domain Contracts)
                       ▼
[ Agent Core: Understanding | Decomposition | Planning | Execution | Evaluation ]
         │                               │                               │
         v                               v                               v
[ MCP Tool Runner ]             [ Memory & RAG ]               [ Replanning Engine ]
  JSON-RPC (Port 8001)            pgvector (1536-dim)            Explainable Diffs
         │                               │                               │
         +───────────────────────────────┼───────────────────────────────+
                                         ▼
[ Storage Adapters: PostgreSQL 16 (Relational + pgvector) | Redis 7 (Cache & Denylist) ]
```

### Monorepo Structure

```text
lifethread/
├── frontend/             # React 18, TypeScript, Vite, Tailwind CSS, Radix UI
├── backend/              # FastAPI application, SQLAlchemy 2.0 models, domain services
├── agent/                # Independent lifethread-agent orchestrator package
├── mcp-server/           # Standalone Model Context Protocol server (JSON-RPC)
├── database/             # Alembic async migration environment and schema versions
├── infrastructure/       # Multi-stage Dockerfiles and container configurations
├── docs/                 # Complete system technical documentation (Module 47)
├── scripts/              # Environment verification, benchmark scripts, demo loaders
├── docker-compose.yml    # Production container orchestration
├── docker-compose.dev.yml# Local development stack with live volume reloads
├── docker-compose.test.yml# Ephemeral automated testing container stack
├── pyproject.toml        # Unified Python tool configuration (ruff, pytest)
└── Makefile              # Standard developer workflow commands
```

---

## 3. Project Setup

### Prerequisites

- **Python:** Version 3.12 or higher
- **Node.js:** Version 20 LTS or higher, with `npm`
- **Docker & Docker Compose:** Docker Engine 24+
- **Git**

### Installation Steps

1. **Clone the Repository:**
   ```bash
   git clone https://github.com/organization/lifethread-ai-agent.git
   cd lifethread-ai-agent
   ```

2. **Initialize Configuration:**
   ```bash
   cp .env.example .env
   python scripts/verify_env.py
   ```

3. **Install Dependencies:**
   ```bash
   # Python packages in editable development mode
   pip install -e ./backend
   pip install -e ./agent
   pip install -e ./mcp-server

   # Frontend packages
   cd frontend && npm install && cd ..
   ```

4. **Launch Database & Cache Infrastructure:**
   ```bash
   docker compose up -d postgres redis
   ```

5. **Apply Database Migrations:**
   ```bash
   alembic upgrade head
   ```

---

## 4. Environment Variables

Configure `.env` using `.env.example` as a baseline:

| Variable | Description | Default / Example |
|---|---|---|
| `ENVIRONMENT` | Environment mode (`development`, `test`, `production`) | `development` |
| `ALLOW_DEMO_DATA` | Enables demo dataset seeding endpoints (disabled in prod) | `True` |
| `SECRET_KEY` | Cryptographic secret for signing JWT access tokens | `your-secure-random-key` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Lifespan of JWT access tokens | `30` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Lifespan of JWT refresh tokens | `7` |
| `DATABASE_URL` | Async PostgreSQL connection string | `postgresql+asyncpg://lifethread_user:lifethread_password_dev_only@localhost:5432/lifethread_db` |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `MCP_SERVER_URL` | Internal URL for MCP service | `http://localhost:8001` |
| `MCP_SERVER_PORT` | Port for standalone MCP service | `8001` |
| `CORS_ORIGINS` | Comma-separated list of allowed frontend origins | `http://localhost:5173,http://localhost:3000` |
| `OPENAI_API_KEY` | Optional API key for LLM and embedding generation | `sk-...` |

---

## 5. Local Development

Run the three primary services in separate terminals:

### Terminal 1: Backend API Gateway (Port 8000)
```bash
uvicorn app.main:app --app-dir backend --reload --port 8000
```
- API Docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/api/v1/health`

### Terminal 2: MCP Server (Port 8001)
```bash
python -m mcp_server.server
```
- Health: `http://localhost:8001/health`

### Terminal 3: Frontend Web Client (Port 5173)
```bash
cd frontend && npm run dev
```
- Web Application: `http://localhost:5173`

### Loading Development Demo Data (Module 46)
To explore realistic long-running goals without manual database creation:
```bash
python scripts/load_demo_data.py
```
This loads 6 realistic scenarios: changing deadlines, limited available time (90 min/day), task failure & diagnostic recovery, newly discovered weaknesses, blocked dependencies (DAG), and successful completions under demo user `demo@lifethread.ai` (`DemoPassword123!`).

---

## 6. Testing Strategy

LifeThread features automated test suites using `pytest` and `pytest-asyncio` with in-memory SQLite isolation:

```bash
# Run the complete test suite
pytest backend/tests/ -v

# Run targeted test suites
pytest backend/tests/test_demo_data.py -v
pytest backend/tests/test_module_44_end_to_end_lifecycle.py -v
pytest backend/tests/test_performance_optimization.py -v
pytest backend/tests/test_semantic_vector_memory.py -v

# Check Python linting and formatting
ruff check backend/ agent/ mcp-server/

# Run TypeScript typecheck
cd frontend && npm run typecheck && cd ..
```

---

## 7. API Documentation

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

### Core Endpoints Summary

- **Authentication (`/api/v1/auth`):**
  - `POST /register`: Register user.
  - `POST /login`: Authenticate and receive JWT tokens.
  - `POST /logout`: Revoke active JWT in Redis denylist.
- **Goals (`/api/v1/goals`):**
  - `POST /`: Create goal.
  - `POST /understand`: Analyze natural language intent into structured acceptance criteria.
  - `GET /`: List user goals.
  - `GET /{id}`: Retrieve goal details, milestones, constraints, and active plans.
- **Tasks & Decomposition (`/api/v1/tasks`):**
  - `POST /decompose/{goal_id}`: Partition goal into milestones and atomic tasks.
  - `PATCH /{id}/status`: Transition task status (`PENDING`, `IN_PROGRESS`, `COMPLETED`, `BLOCKED`, `CANCELLED`).
  - `POST /dependency`: Create `BLOCKS` DAG edge between tasks.
- **Planning (`/api/v1/plans`):**
  - `POST /generate/{goal_id}`: Generate scheduled plan with deadline risk calculation.
  - `GET /goal/{goal_id}`: View plan revisions and allocated execution windows.
- **Memories & RAG (`/api/v1/memories`):**
  - `POST /`: Store episodic, semantic, goal, or preference memory.
  - `POST /search`: Execute vector similarity search via `pgvector`.
- **Autonomous Replanning (`/api/v1/replanning`):**
  - `POST /preview`: Compute non-destructive impact analysis of a constraint change.
  - `POST /execute`: Commit superseding plan version with explainable diff summary.
- **Demo Scenarios (`/api/v1/demo`):**
  - `POST /load`: Populate fresh development environment with 6 realistic scenarios.
  - `POST /reset`: Safely purge demo records.
  - `GET /status`: Inspect demo entity counts.

---

## 8. Model Context Protocol (MCP) Setup

The MCP Server (`mcp-server/`) runs on port 8001 as an independent service communicating via JSON-RPC 2.0 over HTTP:

1. **Verify MCP Server Status:**
   ```bash
   curl http://localhost:8001/health
   ```
2. **List Available Tools:**
   ```bash
   curl -X POST http://localhost:8001/v1/tools/list
   ```
3. **Execute a Tool Call:**
   ```bash
   curl -X POST http://localhost:8001/v1/tools/call \
     -H "Content-Type: application/json" \
     -d '{"tool": "mcp__python_exec", "arguments": {"code": "print(40 + 2)"}}'
   ```

---

## 9. Production Deployment

### Production Docker Compose Stack

Run the hardened multi-stage production containers:
```bash
# Start all services
docker compose up -d

# Verify running services
docker compose ps

# View backend logs
docker compose logs -f backend
```

Images run as an unprivileged non-root user (`appuser`, UID 10001) with read-only root filesystems and minimal base images (`python:3.12-slim`, `node:20-alpine`).

For detailed production instructions (Kubernetes, AWS ECS, Nginx SSL termination), refer to [docs/deployment.md](docs/deployment.md).

---

## 10. Troubleshooting & Common Issues

- **Database Connection Pool Timeout:** Ensure database queries use `get_db` async session context; increase `DB_POOL_SIZE` in `.env` if legitimate concurrency requires it.
- **`pgvector` Extension Missing:** Connect to PostgreSQL and run `CREATE EXTENSION IF NOT EXISTS vector;`.
- **MCP Server Connection Failure:** Ensure the MCP process is running on port 8001 and `MCP_SERVER_URL` in `.env` is reachable.
- **Token Malformed / 401 Unauthorized:** Ensure `SECRET_KEY` in `.env` remains consistent between application restarts.
- **Demo Data Loading Blocked (403):** Demo operations are disabled when `ENVIRONMENT=production` or `ALLOW_DEMO_DATA=False`.

For complete diagnostics and solutions, refer to [docs/troubleshooting.md](docs/troubleshooting.md).

---

## 11. Technical Documentation Index

For in-depth architectural and implementation specifications, see the `docs/` directory:

- [docs/architecture.md](docs/architecture.md) — System architecture, Clean Architecture boundaries, and execution lifecycles.
- [docs/backend.md](docs/backend.md) — FastAPI backend architecture, routers, middleware, and dependency injection.
- [docs/database.md](docs/database.md) — PostgreSQL 16 schema, models, relationships, and Alembic migrations.
- [docs/agent.md](docs/agent.md) — Agent orchestration, goal understanding, decomposition, and 10 trace stages.
- [docs/memory.md](docs/memory.md) — The 4 memory types, deduplication, importance scoring, and audit logging.
- [docs/rag.md](docs/rag.md) — Semantic retrieval engine, 1536-dim embeddings, pgvector cosine search, and hybrid reranking.
- [docs/mcp.md](docs/mcp.md) — Model Context Protocol (MCP) server, client, and standard tool definitions.
- [docs/agent-skills.md](docs/agent-skills.md) — Antigravity agent skills, `SKILL.md` format, and discovery mechanisms.
- [docs/replanning.md](docs/replanning.md) — Autonomous replanning engine, triggers, impact analysis, and explainable diffs.
- [docs/security.md](docs/security.md) — JWT auth, Redis denylist, multi-tenant isolation, and CoT defense sanitization.
- [docs/testing.md](docs/testing.md) — Testing strategy, test suites, mock providers, and quality commands.
- [docs/deployment.md](docs/deployment.md) — Production Dockerfiles, Docker Compose stacks, and CI/CD pipeline.
- [docs/troubleshooting.md](docs/troubleshooting.md) — Step-by-step diagnostics for common operational issues.
