# LifeThread Database Schema & Persistence Model

## 1. Database Architecture

LifeThread utilizes **PostgreSQL 16** with the **`pgvector`** extension as its primary data store, using **SQLAlchemy 2.0 (asyncio)** and **asyncpg** for high-throughput asynchronous execution.

- **Alembic Migrations:** Centrally maintained in `database/migrations/` with asynchronous execution support in `database/env.py`.
- **Multi-Tenant Isolation:** All domain entities reference `users.id` directly or through cascaded goal ownership.
- **pgvector Vector Store:** The `memories` table features a 1536-dimensional float vector column indexed with HNSW for sub-20ms cosine similarity searches.

---

## 2. Entity Relationship Diagram (ERD)

```
       +-------------------+
       |       users       |
       +---------+---------+
                 | 1:N
         +-------+-------+
         |               |
         v               v
   +-----------+   +------------+
   |   goals   |   |  memories  | (with Vector(1536))
   +-----+-----+   +------------+
         |
         +--------+----------------+----------------+
         | 1:N    | 1:N            | 1:N            | 1:N
         v        v                v                v
   +-----------+  +-------------+  +-------------+  +-----------+
   |constraints|  | milestones  |  |decompositions| |   plans   |
   +-----------+  +------+------+  +-------------+  +-----+-----+
                         |                                |
                         | 1:N                            | 1:N
                         v                                v
                   +-----------+                    +-----------+
                   |   tasks   |<-------------------+plan_items |
                   +-----+-----+  (task_id foreign key)
                         |
                         | 1:N
                         v
                   +------------------+
                   | task_dependencies| (DAG edge: BLOCKS)
                   +------------------+
```

---

## 3. Relational Table Definitions

### 3.1 `users` Table
Stores user credentials, preferences, and operational metadata.
- `id` (UUID, Primary Key)
- `email` (VARCHAR(255), Unique, Indexed)
- `password_hash` (VARCHAR(255))
- `display_name` (VARCHAR(100))
- `timezone` (VARCHAR(50), Default "UTC")
- `is_active` (BOOLEAN, Default True)
- `created_at` / `updated_at` (TIMESTAMPTZ)

### 3.2 `goals` Table
Tracks long-running user objectives.
- `id` (UUID, Primary Key)
- `user_id` (UUID, Foreign Key -> `users.id` ON DELETE CASCADE, Indexed)
- `title` (VARCHAR(255), Not Null)
- `objective` (TEXT, Not Null)
- `description` (TEXT)
- `status` (ENUM: `ACTIVE`, `COMPLETED`, `PAUSED`, `FAILED`, `CANCELLED`)
- `priority` (ENUM: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
- `deadline` (TIMESTAMPTZ, Nullable)
- `success_criteria` (JSON, Array of strings)
- `created_at` / `updated_at` (TIMESTAMPTZ)

### 3.3 `goal_constraints` Table
Guiding rules, SLA limits, and capacity budgets.
- `id` (UUID, Primary Key)
- `goal_id` (UUID, Foreign Key -> `goals.id` ON DELETE CASCADE, Indexed)
- `type` (VARCHAR(100), e.g. `capacity_constraint`, `deadline_compression`, `sla`)
- `value` (TEXT, Human-readable constraint description)
- `metadata` (JSON, Structured parameters like `daily_budget_minutes`)

### 3.4 `goal_milestones` Table
Major intermediate phase gates decomposed from a goal.
- `id` (UUID, Primary Key)
- `goal_id` (UUID, Foreign Key -> `goals.id` ON DELETE CASCADE, Indexed)
- `title` (VARCHAR(255), Not Null)
- `description` (TEXT)
- `status` (ENUM: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `BLOCKED`)
- `order_index` (INTEGER, Not Null)
- `deadline` (TIMESTAMPTZ)

### 3.5 `tasks` Table
Atomic, actionable units of execution.
- `id` (UUID, Primary Key)
- `goal_id` (UUID, Foreign Key -> `goals.id` ON DELETE CASCADE, Indexed)
- `milestone_id` (UUID, Foreign Key -> `goal_milestones.id` ON DELETE SET NULL, Indexed)
- `version` (INTEGER, Default 1)
- `title` (VARCHAR(255), Not Null)
- `description` (TEXT)
- `status` (ENUM: `PENDING`, `IN_PROGRESS`, `COMPLETED`, `BLOCKED`, `CANCELLED`)
- `priority` (ENUM: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
- `estimated_minutes` (INTEGER, Default 60)
- `due_at` (TIMESTAMPTZ)
- `completed_at` (TIMESTAMPTZ)
- `metadata` (JSON, Diagnostic traces, failure info, execution tags)

### 3.6 `task_dependencies` Table
Directed acyclic graph (DAG) edges representing prerequisite tasks.
- `id` (UUID, Primary Key)
- `task_id` (UUID, Foreign Key -> `tasks.id` ON DELETE CASCADE, Indexed)
- `depends_on_task_id` (UUID, Foreign Key -> `tasks.id` ON DELETE CASCADE, Indexed)
- `dependency_type` (VARCHAR(50), Default "BLOCKS")

### 3.7 `plans` & `plan_items` Tables
Concrete calendar allocations and versioned scheduling revisions.
- **`plans`:**
  - `id` (UUID, Primary Key)
  - `goal_id` (UUID, Foreign Key -> `goals.id` ON DELETE CASCADE, Indexed)
  - `version` (INTEGER, Plan revision counter)
  - `status` (ENUM: `DRAFT`, `ACTIVE`, `SUPERSEDED`, `ABANDONED`)
  - `is_feasible` (BOOLEAN)
  - `deadline_risk` (FLOAT, Risk score 0.0 to 1.0+)
  - `risk_level` (VARCHAR(20): `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
  - `schedule_utilization` (FLOAT)
  - `total_duration_minutes` (INTEGER)
  - `scheduled_start` / `scheduled_end` (TIMESTAMPTZ)
  - `metadata` (JSON, Replan diff summary, reschedule details)
- **`plan_items`:**
  - `id` (UUID, Primary Key)
  - `plan_id` (UUID, Foreign Key -> `plans.id` ON DELETE CASCADE, Indexed)
  - `task_id` (UUID, Foreign Key -> `tasks.id` ON DELETE CASCADE, Indexed)
  - `scheduled_start` / `scheduled_end` (TIMESTAMPTZ)
  - `priority` (ENUM: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`)
  - `rationale` (TEXT, Justification for this time slot)

### 3.8 `memories` Table
Long-term semantic and episodic memory records with vector embeddings.
- `id` (UUID, Primary Key)
- `user_id` (UUID, Foreign Key -> `users.id` ON DELETE CASCADE, Indexed)
- `memory_type` (ENUM: `EPISODIC`, `SEMANTIC`, `GOAL`, `PREFERENCE`)
- `content` (TEXT, Raw textual memory statement)
- `importance_score` (FLOAT, Range 0.0 to 1.0)
- `confidence` (FLOAT, Range 0.0 to 1.0)
- `source` (VARCHAR(255), Originator, e.g. `agent`, `user`, `evaluation`)
- `status` (ENUM: `ACTIVE`, `ARCHIVED`, `SUPERSEDED`)
- `access_count` (INTEGER, Retrieval reinforcement counter)
- `last_accessed_at` (TIMESTAMPTZ)
- `metadata` (JSON, Tags, scenario ID, adaptive trigger metadata)
- `embedding` (`Vector(1536)`, Cosine indexable embedding)

---

## 4. Database Migrations Workflow

Alembic commands must be executed using the workspace Makefile or CLI:

```bash
# Apply pending migrations to the database
alembic upgrade head

# Generate a new auto-detected migration
alembic revision --autogenerate -m "Add new column or table"

# Rollback the last migration
alembic downgrade -1
```
