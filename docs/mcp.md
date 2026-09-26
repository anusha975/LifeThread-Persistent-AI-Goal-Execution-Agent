# LifeThread Model Context Protocol (MCP) Architecture

## 1. Overview

LifeThread implements the **Model Context Protocol (MCP)** specification to provide an open, standardized bridge between the AI agent orchestrator and external tools, filesystems, and runtime execution environments.

The MCP subsystem consists of two components:
1. **MCP Server (`mcp-server/`):** An independent service running on port 8001 that declares and executes available tools.
2. **MCP Client (`backend/mcp_server/client.py`):** An asynchronous HTTP client integrated into the agent execution pipeline.

```
+------------------------------------+             +------------------------------------+
|          AGENT RUNNER              |             |            MCP SERVER              |
|   (FastAPI Backend / Worker)       |             |         (Port 8001)                |
+-----------------+------------------+             +-----------------+------------------+
                  |                                                  |
                  |  POST /v1/tools/list (JSON-RPC)                  |
                  | -----------------------------------------------> |
                  |  [ { name: "mcp__web_search", ... }, ... ]       |
                  | <----------------------------------------------- |
                  |                                                  |
                  |  POST /v1/tools/call (Tool Execution)            |
                  |  { tool: "mcp__python_exec", args: {...} }       |
                  | -----------------------------------------------> |
                  |                                                  | Executes Sandboxed
                  |  { status: "SUCCESS", result: {...} }            | Code or Tool Logic
                  | <----------------------------------------------- |
                  v                                                  v
```

---

## 2. Protocol & Transport Specification

- **Transport:** Streamable HTTP / JSON-RPC 2.0.
- **Default Port:** `8001` (configurable via `MCP_SERVER_PORT`).
- **Health Check Endpoint:** `GET /health` -> `{"status": "ok", "service": "lifethread-mcp-server"}`.
- **Tools List Endpoint:** `POST /v1/tools/list` -> Returns tool signatures, descriptions, and JSON schemas for arguments.
- **Tool Call Endpoint:** `POST /v1/tools/call` -> Receives tool identifier and JSON arguments; returns standardized tool outputs.

---

## 3. Standard Tool Implementations

The MCP Server ships with a core suite of operational tools:

### 3.1 `mcp__filesystem`
- **Purpose:** Read, write, list, and verify local workspace files.
- **Capabilities:**
  - `read_file(path, offset, limit)`: Securely reads UTF-8 file content.
  - `write_file(path, content, overwrite)`: Creates or updates workspace documents.
  - `list_directory(path)`: Explores directory hierarchies.

### 3.2 `mcp__web_search`
- **Purpose:** Fetches real-time public documentation, API specifications, and research notes.
- **Arguments:** `query: str`, `domain_filter: Optional[str]`, `max_results: int`.

### 3.3 `mcp__python_exec`
- **Purpose:** Executes sandboxed Python code snippets for calculations, data transformation, and test validation.
- **Arguments:** `code: str`, `timeout_seconds: int`.

### 3.4 `mcp__calendar_scheduler`
- **Purpose:** Analyzes time slot availability and tests feasibility against calendar constraints.
- **Arguments:** `start_date: str`, `end_date: str`, `required_minutes: int`, `daily_budget_minutes: int`.

### 3.5 `mcp__database_diagnostic`
- **Purpose:** Runs read-only schema checks, replication lag queries, and health audits for database migration tasks.
- **Arguments:** `check_iops: bool`, `stream_id: str`.

---

## 4. Error Handling & Observability

- **Standardized Error Responses:** If a tool encounters an error (e.g. invalid arguments, execution timeout), it returns a structured JSON-RPC error with standard error codes and descriptive diagnostics.
- **Telemetry Integration:** Every tool invocation is recorded by `AgentObservabilityService.record_tool_call`, tracking:
  - Tool name
  - Execution duration in milliseconds
  - Success/failure flag
  - Error messages and retry counts
  - `is_mcp: True` classification
