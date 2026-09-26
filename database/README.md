# Database Architecture & Migrations

LifeThread utilizes PostgreSQL 16+ as its primary relational store.

## Architecture

- **Driver**: `asyncpg` via SQLAlchemy 2.0 AsyncEngine.
- **Migration Framework**: Alembic with full async support via `database/migrations/env.py`.
- **Vector Search Roadmap**: `pgvector` will be introduced in subsequent modules to support long-term semantic memory and embedding retrieval.

## Migration Workflow

```bash
# Generate a new migration
alembic -c database/alembic.ini revision --autogenerate -m "create_initial_tables"

# Apply pending migrations
alembic -c database/alembic.ini upgrade head

# Rollback last migration
alembic -c database/alembic.ini downgrade -1
```
