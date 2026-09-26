# LifeThread MCP Server

Standalone Model Context Protocol (MCP) server package exposing tools, context, and capabilities over Streamable HTTP.

## Architecture & Principles

```
Agent Orchestrator ──> MCPClient ──> MCP Server (:8001) ──> Generic Tool Services
```

- **Protocol Specification**: Conforms to standard JSON-RPC 2.0 and MCP specifications.
- **Streamable HTTP Transport**: Supports both synchronous JSON-RPC POST requests and Server-Sent Events (SSE) streaming responses (`text/event-stream`).
- **Security & Tracing**:
  - API Key / Bearer token authentication via `MCP_API_KEY` (configurable in `.env`).
  - Correlation ID / `X-Request-ID` tracing header propagated across every request and response.
- **Safe Test Tools**: Exposes safe test tools (`ping`, `echo`, `calculate`).
- **Goal Engine Tools (Module 11)**: Exposes full goal management capabilities (`create_goal`, `get_goal`, `update_goal`, `pause_goal`, `resume_goal`, `complete_goal`) with user ownership checks, delegating directly to `GoalService`.
- **Service Reuse**: Powered by `lifethread_agent.tools.ToolRegistry` and `ToolExecutor`, guaranteeing strict input and output validation without duplicating domain logic.

---

## Exposed MCP Tools Catalog

### Foundational Test Tools
- `ping`: Verifies server connectivity and reports server UTC timestamp.
- `echo`: Echoes back input text with optional repetition.
- `calculate`: Standard arithmetic calculator (`add`, `subtract`, `multiply`, `divide`).

### Goal Engine Tools (Module 11)
- `create_goal`: Creates a new goal with title, objective, constraints, and milestones.
- `get_goal`: Retrieves goal details by `goal_id`, strictly enforcing authenticated `user_id` ownership.
- `update_goal`: Updates fields on an existing goal belonging to the authenticated user.
- `pause_goal`: Pauses an active goal using `GoalService.pause_goal`.
- `resume_goal`: Resumes a paused or draft goal back to active.
- `complete_goal`: Transitions an active or paused goal to completed.

### Planning Tools (Module 12)
- `generate_plan`: Allocates tasks deterministically across calendar hours, creates versioned plans, supersedes previous active plans, and computes deadline risk.
- `get_plan`: Retrieves active or specific historical version of a plan with item rationales and scheduling windows.
- `replan_preview`: Pure dry-run simulation of proposed timeline shifts or task parameter modifications (`is_committed=False`) without mutating persistent database records.
- `update_task`: Safely mutates task attributes (`title`, `description`, `estimated_minutes`, `due_at`, `status`) while enforcing goal ownership.
- `prioritize_task`: Modifies task priority (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`) with tenant ownership enforcement.

### Memory Tools & Memory Engine (Modules 13 & 15)
- Powered by persistent relational **Memory Engine** supporting Episodic, Semantic, Goal, and Preference memories.
- Supports duplicate detection, confidence tracking (`0.0 <= confidence <= 1.0`), importance scoring, and lifecycle policies (access reinforcement, recency decay, preference preservation).
- `store_memory`: Stores or reinforces a memory relationally (`EPISODIC`, `SEMANTIC`, `GOAL`, `PREFERENCE`) with importance score, confidence, provenance source, and metadata under strict user isolation.
- `retrieve_memory`: Retrieves a memory record by ID with authenticated owner verification and access tracking.
- `search_memory`: Searches memories relationally using text substring matching, memory type filtering, minimum importance threshold, minimum confidence threshold, and pagination (no vector search).
- `update_memory`: Updates content, memory type, importance score, confidence, source, status, or metadata of an existing memory.
- `delete_memory`: Permanently deletes or archives a memory record with tenant verification and audit logging.

### Evaluation Tools (Module 14)
- `evaluate_progress`: Produces structured goal progress scoring weighted by priority, completion counts, remaining workload, and deadline pressure.
- `evaluate_task`: Diagnoses individual task health, identifying uncompleted upstream prerequisites, critical path bottleneck status, and overdue states.
- `identify_weakness`: Discovers systemic plan vulnerabilities (`BLOCKED_EXECUTION`, `OVERDUE_TASK`, `RECENT_FAILURE`, `DEPENDENCY_BOTTLENECK`, `DEADLINE_OVERRUN`) with mitigation strategies.
- `calculate_goal_risk`: Calculates multivariate composite risk scores combining schedule proximity, dependency blocker risk, and high-priority exposure without autonomous replanning.

---

## Endpoints

| Method | Path | Description | Authentication |
| :--- | :--- | :--- | :--- |
| `GET` | `/health` | Health check and active tools count | Public |
| `GET` | `/info` | Server capabilities and protocol version | Public |
| `POST` | `/mcp` | Primary JSON-RPC 2.0 handler (`tools/list`, `tools/call`, `initialize`) | Required |
| `GET` | `/sse` | Server-Sent Events initial connection endpoint | Required |

---

## Running the Server

```bash
# Direct Python module execution (Port 8001)
python -m mcp_server.server

# Or via installed console entrypoint
mcp-server
```

---

## Using the MCP Client

```python
import httpx
from mcp_server.client import MCPClient

async with httpx.AsyncClient(base_url="http://localhost:8001") as http_client:
    client = MCPClient(
        base_url="http://localhost:8001",
        api_key="lifethread-mcp-secret-key",
        http_client=http_client,
    )

    # 1. Discover registered tools
    tools = await client.discover_tools()

    # 2. Invoke a tool
    result = await client.call_tool(
        tool_name="calculate",
        arguments={"a": 10.0, "b": 2.5, "operation": "multiply"},
    )
    print("Result:", result["data"])
```
