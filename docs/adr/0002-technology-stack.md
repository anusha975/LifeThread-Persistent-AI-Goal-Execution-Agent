# ADR 0002: Core Technology Stack Selection

## Status
Accepted

## Context
LifeThread requires high concurrency for long-running agent workflows, asynchronous database and Redis access, standardized tool calling via Model Context Protocol, and a responsive frontend client.

## Decision

1. **Backend**:
   - **Python 3.12+**: Modern typing features, performance improvements, and ecosystem dominance for AI agent orchestration.
   - **FastAPI**: Asynchronous native framework with automatic OpenAPI generation.
   - **Pydantic v2**: High-performance validation and structured settings management.
   - **SQLAlchemy 2.0 (asyncio)** + **Alembic**: Async ORM and schema migrations.

2. **Database & Cache**:
   - **PostgreSQL 16**: ACID-compliant persistent store, ready for future `pgvector` embedding extensions.
   - **Redis 7**: Fast session state, agent locks, and transient cache.

3. **Frontend**:
   - **React 18 + TypeScript + Vite + Tailwind CSS**: Fast compilation, strict type safety, and utility-first styling.

4. **Agent & MCP**:
   - **lifethread-agent**: Pure domain package with zero DB coupling.
   - **mcp-server**: Standalone server adhering to Model Context Protocol specification.

## Consequences
- Fast developer velocity with hot module reloading across frontend and backend.
- High async throughput for concurrent AI reasoning runs.
- Ready for future streaming and event-driven patterns.
