# LifeThread Testing Architecture & Quality Assurance

## 1. Overview

LifeThread maintains an extensive, automated test suite spanning unit tests, domain service tests, security audits, and full end-to-end lifecycle integration tests. Tests run completely hermetically without requiring external cloud LLM API keys or live third-party databases.

---

## 2. Test Architecture & Fixtures

### 2.1 Fast In-Memory Database Isolation
- Automated tests use SQLite via `aiosqlite` (`sqlite+aiosqlite:///:memory:`) for instantaneous setup and teardown.
- Database schemas are dynamically created from SQLAlchemy `Base.metadata.create_all` before each test suite, ensuring clean isolation between tests.
- When running in Docker Compose or CI environments, PostgreSQL tests run against dedicated ephemeral test database containers (`docker-compose.test.yml`).

### 2.2 Provider Test Doubles
To ensure deterministic, high-speed test execution:
- **`MockEmbeddingProvider`:** Generates mathematically deterministic 1536-dimensional float vectors that are unit-normalized ($\sqrt{\sum x_i^2} \approx 1.0$), allowing precise testing of cosine similarity and ranking math.
- **`EvaluationLLMProvider`:** Simulates model completions with predictable response formats, eliminating network latency and third-party rate limits.

---

## 3. Test Suites Directory & Coverage

| Test File | Focus Area | Description |
|---|---|---|
| `backend/tests/test_demo_data.py` | Module 46 Demo Data | Verifies 6 realistic scenarios, production guards, tenant isolation, and REST API. |
| `backend/tests/test_module_44_end_to_end_lifecycle.py` | Complete E2E Lifecycle | Validates complete lifecycle from goal creation to understanding, decomposition, execution, replanning, and completion. |
| `backend/tests/test_performance_optimization.py` | Module 43 Optimization | Benchmarks database query times, Redis caching, vector search latency, and memory retrieval. |
| `backend/tests/test_semantic_vector_memory.py` | Vector Memory & RAG | Validates cosine distance search, importance weighting, recency decay, and duplicate reinforcement. |
| `backend/tests/test_permission_system.py` | Security & Auth | Tests JWT validation, expired tokens, malformed headers, and token denylisting. |
| `backend/tests/test_agent_evaluation.py` | Agent Evaluation | Tests scoring functions, constraint adherence checks, and metric calculations. |
| `backend/tests/test_context_engine.py` | Context Window RAG | Tests prompt context assembly, category token quotas, and priority truncation. |
| `backend/tests/test_health_and_metrics.py` | Infrastructure Health | Tests liveness/readiness probes and Prometheus telemetry endpoints. |

---

## 4. Running the Tests

### 4.1 Run Complete Test Suite
```bash
# Execute all backend tests
pytest backend/tests/ -v

# Run with quiet one-line output
pytest backend/tests/ -q
```

### 4.2 Run Specific Targeted Modules
```bash
# Run Module 46 Demo Data suite
pytest backend/tests/test_demo_data.py -v

# Run End-to-End Integration Lifecycle suite
pytest backend/tests/test_module_44_end_to_end_lifecycle.py -v

# Run Performance and Caching Benchmarks
pytest backend/tests/test_performance_optimization.py -v
```

### 4.3 Run Linting & Code Quality
```bash
# Check Python code formatting and linting
ruff check backend/ agent/ mcp-server/

# Run TypeScript type check on frontend
cd frontend && npm run typecheck && cd ..
```
