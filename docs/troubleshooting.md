# LifeThread Troubleshooting & Diagnostics Guide

## 1. Overview

This guide provides diagnostic procedures and resolution steps for common operational issues encountered during development, testing, and production deployment of LifeThread.

---

## 2. Common Issues & Resolutions

### 2.1 Database Connectivity & Pool Timeouts
- **Symptoms:** `TimeoutError: QueuePool limit of size 10 overflow 20 reached`, or `asyncpg.exceptions.CannotConnectNowError`.
- **Root Cause:** Excessive concurrent database sessions not closing properly, or PostgreSQL is reaching `max_connections`.
- **Diagnostic Commands:**
  ```bash
  # Check active PostgreSQL connections
  docker compose exec postgres psql -U lifethread_user -d lifethread_db -c "SELECT count(*) FROM pg_stat_activity;"
  ```
- **Resolution:**
  - Ensure all database interactions utilize the `get_db` async dependency context manager (`async with session_factory() as session:`).
  - Increase `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` in `.env` if legitimate load exceeds defaults.
  - Enable `DB_POOL_PRE_PING=True` to automatically purge stale connections.

---

### 2.2 `pgvector` Extension Missing
- **Symptoms:** `UndefinedObjectError: type "vector" does not exist`.
- **Root Cause:** The PostgreSQL database was initialized without the `pgvector` extension enabled.
- **Diagnostic Commands:**
  ```bash
  docker compose exec postgres psql -U lifethread_user -d lifethread_db -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
  ```
- **Resolution:**
  - Connect to PostgreSQL as superuser and enable the extension:
    ```sql
    CREATE EXTENSION IF NOT EXISTS vector;
    ```
  - Ensure your Docker container is using a PostgreSQL image with pgvector pre-installed (e.g. `pgvector/pgvector:pg16`).

---

### 2.3 Redis Connection Failure & Cache Degradation
- **Symptoms:** Warnings in logs: `Redis connection error; operating in degraded mode` or token logout checks failing.
- **Root Cause:** Redis container is stopped, unreachable on port 6379, or password mismatch.
- **Diagnostic Commands:**
  ```bash
  # Test Redis ping
  docker compose exec redis redis-cli ping
  ```
- **Resolution:**
  - Verify `REDIS_URL` in `.env` matches the running Redis instance.
  - Restart the Redis container: `docker compose restart redis`.
  - The application provides graceful degradation for query caching, but token denylisting requires an active Redis instance for full security.

---

### 2.4 MCP Server Unreachable or Tool Call Timeout
- **Symptoms:** `MCPClientError: Failed to connect to MCP server on http://localhost:8001` or `HTTP 504 Gateway Timeout`.
- **Root Cause:** The MCP server process (`mcp-server`) has not been started or is blocked on a long-running subprocess.
- **Diagnostic Commands:**
  ```bash
  # Check MCP server health endpoint
  curl -i http://localhost:8001/health
  
  # Check tools listing
  curl -X POST http://localhost:8001/v1/tools/list
  ```
- **Resolution:**
  - Launch the MCP server:
    ```bash
    python -m mcp_server.server
    ```
  - Verify `MCP_SERVER_URL` in `backend/.env` points to the correct host and port (`http://localhost:8001` for local, `http://mcp-server:8001` inside Docker).

---

### 2.5 401 Unauthorized / Token Malformed Errors
- **Symptoms:** API requests fail with `401 Unauthorized: Could not validate credentials` or `Malformed user UUID`.
- **Root Cause:** Expired JWT token, changed `SECRET_KEY`, or an invalid token format.
- **Diagnostic Commands:**
  - Inspect backend audit logs: `tail -f backend/audit.log | grep AUTHENTICATE_TOKEN`.
- **Resolution:**
  - Log out and log back in to obtain a freshly signed JWT token.
  - Ensure `SECRET_KEY` in `.env` is identical across restarts; generating a random key on each startup invalidates all previous user sessions.

---

### 2.6 Demo Data Operations Blocked (`403 Forbidden`)
- **Symptoms:** `POST /api/v1/demo/load` or `python scripts/load_demo_data.py` fails with `Demo data operations are strictly disabled in production environments`.
- **Root Cause:** Safety guardrails are preventing demo data from running in production.
- **Resolution:**
  - Check your environment settings:
    - Ensure `ENVIRONMENT` is set to `development` or `test` (not `production`).
    - Ensure `ALLOW_DEMO_DATA=True` in `.env`.
  - Demo data can never be loaded into a live production database.

---

### 2.7 Frontend CORS or Proxy Errors
- **Symptoms:** Browser console displays `Access to XMLHttpRequest at 'http://localhost:8000/api/v1/...' has been blocked by CORS policy`.
- **Root Cause:** Frontend origin is not listed in backend `CORS_ORIGINS`.
- **Resolution:**
  - In `backend/.env`, update `CORS_ORIGINS` to include your frontend URL:
    ```text
    CORS_ORIGINS=http://localhost:5173,http://localhost:3000
    ```
  - Restart the backend server for settings to take effect.
