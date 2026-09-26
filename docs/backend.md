# LifeThread Backend Architecture & API Specification

## 1. Overview

The LifeThread backend is an asynchronous, high-throughput service built with **Python 3.12+**, **FastAPI**, **Pydantic v2**, and **SQLAlchemy 2.0 (asyncio)**. It coordinates API requests, user identity, database persistence, agent orchestration, and memory vector retrieval.

---

## 2. Directory Layout

```text
backend/
├── app/
│   ├── api/
│   │   └── v1/                 # Versioned REST routers
│   │       ├── auth.py         # Login, registration, token refresh, logout
│   │       ├── goals.py        # Goal CRUD, milestones, understanding
│   │       ├── tasks.py        # Task decomposition, status updates, dependencies
│   │       ├── plans.py        # Plan generation, schedule inspection, rollback
│   │       ├── memories.py     # Persistent memory storage, update, deletion
│   │       ├── context.py      # Context window builder & prompt assembly
│   │       ├── replanning.py   # Replan previews, trigger handling, diff engine
│   │       ├── evaluation.py   # Autonomous execution evaluation suite
│   │       ├── telemetry.py    # Observability, agent traces, latency metrics
│   │       ├── audit.py        # Security audit log inspection
│   │       ├── demo.py         # Module 46 demo dataset load & reset
│   │       ├── health.py       # Liveness and readiness probes
│   │       └── router.py       # Aggregate v1 API router
│   ├── core/
│   │   ├── config.py           # Pydantic Settings management (.env)
│   │   ├── security.py         # Password hashing (bcrypt) & JWT tokens
│   │   ├── token_store.py      # Redis-backed token denylist
│   │   └── audit.py            # Security audit service & event logger
│   ├── db/
│   │   ├── base.py             # Declarative SQLAlchemy Base
│   │   ├── session.py          # Async engine, connection pooling, get_db
│   │   └── models/             # Relational domain models
│   ├── dependencies/
│   │   ├── auth.py             # get_current_user, get_optional_current_user
│   │   └── llm.py              # LLM provider injection
│   ├── demo/
│   │   ├── scenarios.py        # 6 long-running demo scenario definitions
│   │   └── loader.py           # DemoDataLoader lifecycle manager
│   ├── schemas/                # Pydantic request/response validation models
│   ├── services/               # Core domain business logic
│   └── main.py                 # FastAPI application factory & middleware
```

---

## 3. Core API Endpoints

### 3.1 Authentication (`/api/v1/auth`)
- `POST /register`: Creates a new user with password hashing and initial settings.
- `POST /login`: Validates credentials; returns JWT access and refresh tokens.
- `POST /refresh`: Issues a refreshed access token.
- `POST /logout`: Denylists the active JWT access token in Redis.
- `GET /me`: Returns the authenticated user profile.

### 3.2 Goals (`/api/v1/goals`)
- `POST /`: Creates a goal with target objective, priority, deadline, and constraints.
- `POST /understand`: Analyzes natural language intent and outputs structured criteria.
- `GET /`: Lists all active, paused, or completed goals for the current user.
- `GET /{goal_id}`: Retrieves comprehensive goal details, constraints, milestones, and plans.
- `PATCH /{goal_id}`: Updates goal status or deadline.
- `DELETE /{goal_id}`: Deletes goal with cascading milestone and task cleanup.

### 3.3 Tasks & Decomposition (`/api/v1/tasks`)
- `POST /decompose/{goal_id}`: Decomposes a goal into ordered milestones and atomic tasks.
- `GET /goal/{goal_id}`: Returns all tasks and their DAG dependency links.
- `PATCH /{task_id}/status`: Transitions task status (`PENDING` -> `IN_PROGRESS` -> `COMPLETED`, `BLOCKED`, `CANCELLED`).
- `POST /dependency`: Establishes `BLOCKS` relationship between two tasks.

### 3.4 Planning & Scheduling (`/api/v1/plans`)
- `POST /generate/{goal_id}`: Generates a scheduled plan allocating daily time windows.
- `GET /goal/{goal_id}`: Fetches all plan revisions (Plan v1, Plan v2) and calculated deadline risk.
- `GET /{plan_id}/items`: Retrieves scheduled execution slots with rationales.

### 3.5 Memory & RAG (`/api/v1/memories`)
- `POST /`: Stores a memory (`EPISODIC`, `SEMANTIC`, `GOAL`, `PREFERENCE`) with vector embedding.
- `GET /`: Searches or lists memories with optional category filter.
- `POST /search`: Executes semantic vector similarity search via `pgvector`.
- `DELETE /{memory_id}`: Removes memory entry.

### 3.6 Replanning Engine (`/api/v1/replanning`)
- `POST /preview`: Calculates the impact of a deadline change or failure without saving.
- `POST /execute`: Generates a superseding plan version with an explainable diff.
- `POST /rollback`: Restores a previous plan version.

### 3.7 Demo Dataset Operations (`/api/v1/demo`)
- `POST /load`: Seeds the 6 realistic scenarios for development/testing.
- `POST /reset`: Safely clears demo data without affecting real user records.
- `GET /status`: Inspects demo dataset entity counts.

---

## 4. Middleware & Cross-Cutting Concerns

1. **Security Headers Middleware:** Enforces `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy`, and `Strict-Transport-Security`.
2. **CORS Middleware:** Configured with strict whitelist matching frontend development and production origins.
3. **Rate Limiting:** Managed via `SlowAPI` with Redis or in-memory backing to prevent brute-force attacks on authentication and LLM generation endpoints.
4. **Structured JSON Logging:** Requests, responses, latency, and correlation IDs are logged in structured JSON for ELK/Prometheus ingestion.
