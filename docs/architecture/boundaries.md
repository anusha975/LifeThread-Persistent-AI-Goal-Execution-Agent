# Package Boundaries & Dependency Inversion

LifeThread strictly enforces boundaries between subsystems to prevent architectural drift as the codebase expands through future modules.

## Package Matrix

| Package | May Depend On | Must NEVER Depend On | Purpose |
| :--- | :--- | :--- | :--- |
| `frontend` | Backend HTTP API | Database, Redis, Agent internals | User interface, state presentation |
| `backend` | `agent` (contracts), DB, Redis, LLM, MCP | Frontend | API gateway, persistence, session coordination |
| `agent` | Pure Python, Pydantic domain models | Database (`sqlalchemy`, `asyncpg`), Redis, FastAPI | Goal decomposition, planning, agent orchestration |
| `mcp-server`| MCP protocol libraries, Tool dependencies | Backend DB schema, Frontend | Exposing tools & resources via standard protocol |
| `database` | SQLAlchemy models, Alembic | Agent, Frontend, MCP | Relational migrations and schema management |

## Rules of Engagement

1. **No Database Imports in Agent**:
   - `from sqlalchemy import ...` or `from app.db import ...` inside `agent/` will fail code review and linting.
   - Persistence operations needed by the agent must be fulfilled by the backend or domain repository interfaces.

2. **No Direct Agent Execution from Frontend**:
   - The browser never invokes agent routines directly. All interactions flow through versioned backend routes (`/api/v1/...`).

3. **Standalone MCP Portability**:
   - The MCP server can be started on its own port (default: `8001`) or invoked via stdio. It must remain decoupled from specific backend routing.

4. **Secrets Management**:
   - No API keys, credentials, or tokens are ever checked into Git.
   - All runtime secrets are configured via `.env` loaded into typed Pydantic `BaseSettings`.
