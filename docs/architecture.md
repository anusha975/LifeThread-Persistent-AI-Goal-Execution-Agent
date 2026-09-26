# LifeThread Architecture Specification

## 1. System Overview

LifeThread is an autonomous, persistent AI goal-execution platform designed to shepherd long-running human and organizational objectives from abstract intent to verified completion. Unlike stateless conversational agents or simple task runners, LifeThread treats a goal as a dynamic, living entity that evolves across days, weeks, or months.

```
+---------------------------------------------------------------------------------------+
|                                    PRESENTATION                                       |
|               React 18 + TypeScript + Vite + Tailwind CSS + Radix UI                  |
+-------------------------------------------+-------------------------------------------+
                                            | (REST JSON / Server-Sent Events)
                                            v
+---------------------------------------------------------------------------------------+
|                                BACKEND API GATEWAY                                    |
|                        FastAPI + Pydantic v2 + SlowAPI                                |
+-------------------------------------------+-------------------------------------------+
                                            | (Inversion of Control / Domain Contracts)
                                            v
+---------------------------------------------------------------------------------------+
|                               AGENT ORCHESTRATION                                     |
|           Goal Understanding | Decomposition | Planning | Execution | Evaluation      |
+-------------------------------------------+-------------------------------------------+
         |                                  |                                  |
         v                                  v                                  v
+--------------------+            +--------------------+            +-------------------+
|  MCP TOOL RUNNER   |            |   MEMORY ENGINE    |            | REPLANNING ENGINE |
| Model Context      |            | pgvector 1536-dim  |            | Reversible Diff   |
| Protocol (JSON-RPC)|            | Semantic Search    |            | Impact Analysis   |
+--------------------+            +--------------------+            +-------------------+
         |                                  |                                  |
         +----------------------------------+----------------------------------+
                                            v
+---------------------------------------------------------------------------------------+
|                               STORAGE & CACHE ADAPTERS                                |
|          PostgreSQL 16 (Relational + pgvector)  |  Redis 7 (Cache & Denylist)         |
+---------------------------------------------------------------------------------------+
```

---

## 2. Core Architecture Principles

1. **Clean Architecture & Domain Isolation:**
   - The agent core logic resides in domain-driven modules decoupled from database drivers, web frameworks, and third-party API clients.
   - Data access is mediated through SQLAlchemy async sessions and domain service abstractions.

2. **Strict Multi-Tenant Isolation:**
   - Every database query, vector search index, and cached session is scoped to an authenticated `user_id`.
   - Cross-tenant data leakage is prevented at both the database query layer and the memory retrieval layer.

3. **Deterministic Constraint & Scheduling Model:**
   - Goal planning does not rely on open-ended LLM guessing for calendar mathematics.
   - Deadlines, daily capacity limits (e.g. 90 minutes/day), and dependency graphs (DAG) are enforced through deterministic scheduling algorithms.

4. **Closed Cognitive Feedback Loop:**
   - Every execution step emits structured telemetry.
   - Task failures trigger autonomous diagnostic logging and recovery paths.
   - Identified personal or operational weaknesses are persisted as semantic memories to adapt future plans.

5. **Chain-of-Thought (CoT) Defense:**
   - The user-facing observability stream is sanitized by `CoTSanitizer` to prevent prompt leakage, internal tokens, or secret disclosure while providing clear operational explanations.

---

## 3. Subsystem Breakdown

### 3.1 Presentation Layer (`frontend/`)
- Single-page application built with React 18, TypeScript, Vite, and Tailwind CSS.
- Implements unified layout, goal creation modals, timeline visualizers, DAG dependency inspectors, memory management panels, and real-time execution telemetry feeds.
- Interacts exclusively with the `/api/v1` REST API gateway.

### 3.2 Backend Service & API Gateway (`backend/`)
- Asynchronous Python service utilizing FastAPI and SQLAlchemy 2.0.
- Handles JWT authentication, rate limiting, request validation via Pydantic v2, and dependency injection (`get_db`, `get_current_user`).
- Houses the business services coordinating goal lifecycles, memory storage, replanning previews, and agent observability.

### 3.3 Agent Orchestration (`agent/` and `backend/app/services/`)
- **Goal Understanding:** Translates unstructured natural language into structured objectives, success criteria, and initial constraints.
- **Goal Decomposition:** Hierarchically partitions objectives into phased milestones and actionable tasks with duration estimates.
- **Autonomous Planning:** Schedules tasks into discrete execution slots, checks resource feasibility, and assesses deadline risk.
- **Agent Trace Service:** Tracks 10 lifecycle stages with comprehensive telemetry (`AgentObservabilityService`).

### 3.4 Model Context Protocol (`mcp-server/`)
- Independent service adhering to the Model Context Protocol (MCP) standard.
- Communicates via streamable HTTP JSON-RPC on port 8001.
- Exposes modular tool capabilities: filesystem operations, web search, Python code sandbox, calendar slot management, and database diagnostics.

### 3.5 Memory & RAG Engine (`backend/app/services/memory.py` & `semantic_retriever.py`)
- Persistent memory store divided into 4 types: `EPISODIC`, `SEMANTIC`, `GOAL`, `PREFERENCE`.
- Employs 1536-dimensional vector embeddings with cosine similarity distance search via PostgreSQL `pgvector`.
- Dynamic hybrid reranking balances semantic relevance, importance score, and recency decay.

### 3.6 Data Persistence & Infrastructure (`database/` & `infrastructure/`)
- PostgreSQL 16 relational database with asyncpg driver and Alembic schema migrations.
- Redis 7 for high-performance JWT token denylisting, session caching, and query result caching.
- Multi-stage Docker containerization and Docker Compose stacks for local dev, test, and production deployments.

---

## 4. End-to-End Goal Execution Lifecycle

```
[ User Prompt ]
       |
       v
1. Goal Understanding   --> Extracts title, objective, constraints, criteria
       |
       v
2. Goal Decomposition   --> Builds Milestones, Tasks, and DAG Dependency graph
       |
       v
3. Planning             --> Generates Plan v1: schedules slots, computes deadline risk
       |
       v
4. Agent Execution      --> Runs active tasks; invokes MCP tools
       |
       v
5. Evaluation & Memory  --> Scores execution; records episodic outcome & semantic weakness
       |
       v
6. Constraint Change    --> External trigger (e.g. compressed deadline or failure)
       |
       v
7. Impact Analysis      --> Autonomous replan preview; computes explainable diff
       |
       v
8. Re-planning          --> Issues Plan v2 (SUPERSEDING Plan v1); recalculates risk
       |
       v
9. Goal Completion      --> 100% of tasks completed; records final achievement memory
```
