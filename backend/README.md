# LifeThread Backend Service

FastAPI-powered asynchronous REST API and service adapter layer for the LifeThread platform.

## Architecture & Structure (Module 7: Planning Engine)

```text
backend/
├── app/
│   ├── main.py                   # FastAPI application factory, middleware, exception handlers
│   ├── core/
│   │   ├── config.py             # Pydantic Settings loaded from environment (.env)
│   │   ├── logging.py            # Structured logging with async contextvar Request ID
│   │   ├── security.py           # Bcrypt password hashing & JWT token handling
│   │   ├── token_store.py        # Token revocation registry
│   │   └── exceptions.py         # Global domain & HTTP exception handlers
│   ├── api/
│   │   └── v1/
│   │       ├── router.py         # Versioned router aggregator (/api/v1)
│   │       ├── auth.py           # Authentication & user profile endpoints
│   │       ├── goals.py          # Goal Engine CRUD, understanding, decomposition, & planning
│   │       └── health.py         # Liveness (/health) and Readiness (/ready) probes
│   ├── middleware/
│   │   ├── request_id.py         # X-Request-ID extraction/generation & context propagation
│   │   └── timing.py             # Request timing and structured completion logs
│   ├── schemas/
│   │   ├── auth.py               # LoginRequest, TokenResponse, RefreshTokenRequest, LogoutRequest
│   │   ├── user.py               # UserCreate, UserResponse, UserBase
│   │   ├── goal.py               # GoalCreate, GoalUpdate, GoalResponse, GoalListResponse, GoalConstraint, GoalMilestone
│   │   ├── goal_understanding.py # GoalUnderstandRequest, GoalUnderstandingSchema, GoalStructuredSpecification
│   │   ├── decomposition.py      # DecompositionRequest, GoalDecompositionResponse, TaskResponse, TaskDependencyGraphResponse
│   │   ├── plan.py               # PlanCreateRequest, PlanResponse, PlanItemResponse, PlanListResponse
│   │   ├── health.py             # HealthResponse and ReadinessResponse schemas
│   │   └── error.py              # Standardized ErrorResponse schema
│   ├── dependencies/
│   │   ├── auth.py               # get_current_user & get_current_active_user
│   │   ├── llm.py                # get_llm_provider_dep injectable LLM provider dependency
│   │   └── common.py             # Dependency injection providers (Settings, RequestID)
│   ├── services/
│   │   ├── goal.py               # GoalService state transitions, validation, and multi-tenant persistence
│   │   ├── goal_understanding.py # GoalUnderstandingService (prompting, Pydantic validation, date normalization)
│   │   ├── goal_clarification.py # GoalClarificationService (ambiguity detection & targeted questions)
│   │   ├── decomposition.py      # DecompositionService (goal decomposition, versioning, persistence)
│   │   ├── dependency_graph.py   # DependencyGraphService (DAG validation, cycle detection, topological sort)
│   │   ├── critical_path.py      # CriticalPathService (CPM forward/backward passes, critical path sequence)
│   │   ├── planning.py           # PlanningService (deterministic scheduling, calendar allocation, risk metrics)
│   │   └── llm/
│   │       ├── provider.py       # LLMProvider / BaseLLMProvider abstract interface
│   │       ├── mock.py           # MockLLMProvider for deterministic offline testing
│   │       ├── openai.py         # OpenAILLMProvider adapter
│   │       └── factory.py        # LLMProviderRegistry and factory helper
│   └── db/
│       ├── base.py               # BaseDBModel, Base, UUID & Timestamp mixins
│       ├── health.py             # Database ping & latency health check
│       ├── session.py            # Async SQLAlchemy engine and session dependency
│       ├── models/
│       │   ├── base.py           # Base ORM model declarations
│       │   ├── user.py           # User database model
│       │   ├── goal.py           # Goal, GoalStatus, GoalPriority, GoalConstraint, GoalMilestone, MilestoneStatus
│       │   ├── task.py           # Task, TaskStatus, TaskDependency, GoalDecomposition models
│       │   └── plan.py           # Plan, PlanItem, PlanStatus models
│       └── migrations/
│           ├── env.py            # Async Alembic runner
│           └── versions/
│               ├── 0001_initial_baseline.py
│               ├── 0002_create_users_table.py
│               ├── 0003_create_goals_and_milestones.py
│               ├── 0004_create_tasks_and_dependencies.py
│               └── 0005_create_plans_and_plan_items.py
├── tests/
│   ├── conftest.py               # Test fixtures and TestClient setup
│   ├── test_planning.py          # Planning Engine tests (dependencies, infeasibility, risk, capacity, versioning)
│   ├── test_decomposition.py     # Goal decomposition, cycle detection, critical path, versioning tests
│   ├── test_goal_understanding.py# AI Goal Understanding tests (extraction, ambiguity, malformed JSON, dates)
│   ├── test_goals.py             # Goal CRUD, lifecycle state machine, validation, and tenant isolation tests
│   ├── test_auth.py              # Authentication lifecycle tests (register, login, refresh, logout, me)
│   ├── test_alembic.py           # Migration configuration tests
│   ├── test_db_base.py           # Base model, UUID, and timestamp tests
│   ├── test_db_health.py         # Database health probe tests
│   ├── test_db_session.py        # Sessionmaker and transaction tests
│   ├── test_exceptions.py        # Structured 404, 422, and domain error tests
│   ├── test_health.py            # Health and readiness probe tests
│   └── test_middleware.py        # Request ID and timing middleware tests
│   ├── test_exceptions.py        # Structured 404, 422, and domain error tests
│   ├── test_health.py            # Health and readiness probe tests
│   └── test_middleware.py        # Request ID and timing middleware tests
├── alembic.ini
└── pyproject.toml
```

## Core Goal Engine & Decomposition Endpoints

All Goal endpoints require Bearer JWT authentication (`Authorization: Bearer <access_token>`) and enforce multi-tenant isolation (users may only view and mutate their own goals; unauthorized access returns 404).

- `POST /api/v1/goals/understand`: Interpret a natural language goal description into a validated structured specification (`GoalUnderstandingSchema`) with ambiguity detection and date normalization. Does NOT automatically persist the final goal until explicitly confirmed.
- `POST /api/v1/goals`: Create a long-running goal with constraints, milestones, and success criteria
- `GET /api/v1/goals`: List authenticated user's goals with optional `status` filter and pagination (`limit`, `offset`)
- `GET /api/v1/goals/{goal_id}`: Retrieve single goal with its constraints and milestones
- `PATCH /api/v1/goals/{goal_id}`: Update title, objective, description, priority, deadline, or success criteria
- `POST /api/v1/goals/{goal_id}/pause`: Transition goal status from `ACTIVE` to `PAUSED`
- `POST /api/v1/goals/{goal_id}/resume`: Transition goal status from `PAUSED` or `DRAFT` to `ACTIVE`
- `POST /api/v1/goals/{goal_id}/complete`: Transition goal status from `ACTIVE` or `PAUSED` to `COMPLETED`
- `DELETE /api/v1/goals/{goal_id}`: Delete goal and cascade-remove associated constraints and milestones
- `POST /api/v1/goals/{goal_id}/decompose`: Decompose a goal into progressive milestones, actionable tasks, and a validated directed dependency graph (DAG) with cycle detection, critical path calculation, and version preservation.
- `GET /api/v1/goals/{goal_id}/tasks`: Retrieve tasks generated for a goal with optional `version` and `status` filtering.
- `GET /api/v1/goals/{goal_id}/dependencies`: Retrieve the complete directed dependency graph, critical path, and topological order for a goal.

## Authentication & User Endpoints

- `POST /api/v1/auth/register`: Register new user account (bcrypt password hashing, email uniqueness)
- `POST /api/v1/auth/login`: Authenticate credentials and receive access + refresh tokens
- `POST /api/v1/auth/refresh`: Rotate refresh token and issue new access token
- `POST /api/v1/auth/logout`: Revoke access and/or refresh tokens via denylist
- `GET /api/v1/auth/me`: Retrieve authenticated user profile (protected route)

## Health & System Endpoints

- `GET /`: Service metadata discovery
- `GET /health`: Liveness probe (root alias)
- `GET /api/v1/health`: Structured liveness probe (`{"status": "ok", "service": "lifethread-api", "version": "0.1.0"}`)
- `GET /api/v1/ready`: Structured readiness probe with live database latency check
- `GET /docs`: Interactive Swagger documentation

## Local Execution

```bash
# Run backend development server
uvicorn app.main:app --app-dir backend --reload --port 8000

# Run all backend unit and integration tests
pytest backend/tests/
```

