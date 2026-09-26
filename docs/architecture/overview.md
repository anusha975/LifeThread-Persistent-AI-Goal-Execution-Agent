# System Architecture Overview

LifeThread is an autonomous, persistent AI goal-execution system designed to understand, plan, execute, evaluate, remember, and replan long-running tasks.

## High-Level Flow & Responsibility Separation

```
[ User Browser / Client ]
            │
            ▼ (HTTP / JSON)
┌───────────────────────────────────────────────┐
│              Frontend (React)                 │
└───────────────────────┬───────────────────────┘
                        │
                        ▼ (REST / SSE)
┌───────────────────────────────────────────────┐
│               Backend (FastAPI)               │
│  - Request Validation & Auth Gateway          │
│  - Session & State Management                 │
│  - Dependency Injection (DB / Redis Sessions) │
└───────┬───────────────────────────────┬───────┘
        │                               │
        ▼ (Pure Domain Types)           ▼ (Service Ports)
┌───────────────────────────────┐   ┌───────────────────────────────┐
│       Agent Orchestrator      │   │ External & Storage Adapters   │
│  (lifethread-agent package)   │   │  - PostgreSQL 16 (SQLAlchemy) │
│  - Goal Decomposition         │   │  - Redis 7 (State / Cache)    │
│  - Turn-based Execution       │   │  - AI Provider (LLM Abstr.)   │
│  - Zero Direct DB Imports     │   │  - MCP Server (Tools/Context) │
└───────────────────────────────┘   └───────────────────────────────┘
```

## Core Architectural Guarantees

1. **Frontend Isolation**: The frontend exclusively communicates with the backend REST API. It possesses zero direct visibility into database queries, Redis caching, or agent execution internals.
2. **Backend Gateway**: The backend manages external HTTP requests, serializes responses via Pydantic, and injects dependencies.
3. **Agent Decoupling**: The agent package is independent and domain-focused. It operates on pure domain models and depends on interfaces for storage or model execution.
4. **Independent MCP Server**: The MCP server is built as an independent runnable package to support horizontal scaling, sidecar deployments, and modular tool registration.
5. **Pluggable LLM Providers**: The LLM interaction layer uses an abstract provider interface (`BaseLLMProvider`), allowing model changes without code refactoring.
