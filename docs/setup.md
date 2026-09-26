# Developer Local Setup Guide

Follow this guide to get the LifeThread monorepo running locally.

## Prerequisites

- **Python 3.12+**
- **Node.js 20+** and **npm**
- **Docker** and **Docker Compose** (for PostgreSQL and Redis)
- **Make** (optional, recommended)

## Step-by-Step Initialization

### 1. Environment Setup
Copy the example environment file:
```bash
cp .env.example .env
```
Inspect `.env` to verify default ports and configuration settings.

### 2. Verify Environment Variables
Run the verification script to ensure all expected variables are declared without leaking secret values:
```bash
python scripts/verify_env.py
```

### 3. Start Infrastructure
Launch PostgreSQL and Redis in the background:
```bash
docker compose up -d postgres redis
```

### 4. Install Dependencies

**Python packages (editable mode):**
```bash
pip install -e ./backend
pip install -e ./agent
pip install -e ./mcp-server
```

**Frontend dependencies:**
```bash
cd frontend && npm install && cd ..
```

### 5. Run Services

**Start Backend (Port 8000):**
```bash
uvicorn app.main:app --app-dir backend --reload --port 8000
```

**Start MCP Server (Port 8001):**
```bash
python -m mcp_server.server
```

**Start Frontend (Port 5173):**
```bash
cd frontend && npm run dev
```

### 6. Run Test Suite
```bash
pytest tests/
```
