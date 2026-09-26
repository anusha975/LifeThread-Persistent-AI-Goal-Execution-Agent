# LifeThread Agent Orchestrator Package

Autonomous goal decomposition, task orchestration, and context evaluation core.

## Strict Architectural Principle

**The Agent package contains ZERO database implementation details.**

```
Frontend ──> Backend API ──> Agent Orchestrator ──> Service Ports ──> Adapters (DB / Redis / MCP / LLM)
```

1. **Pure Domain Logic**: All models in this package are pure Pydantic contracts or domain abstractions.
2. **Inversion of Control**: State persistence, memory retrieval, and external tool calls are provided via injected service ports.
3. **No Direct I/O**: The agent never talks directly to PostgreSQL or Redis.

---

## Canonical Agent Loop

```
  ┌────────────────────────────────────────────────────────┐
  │                       AGENT LOOP                       │
  │                                                        │
  │   1. OBSERVE      (Fetch state & recall memory)        │
  │          │                                             │
  │          ▼                                             │
  │   2. UNDERSTAND   (Synthesize working context)         │
  │          │                                             │
  │          ▼                                             │
  │   3. DECIDE       (Produce structured AgentDecision)   │
  │          │                                             │
  │          ▼                                             │
  │   4. ACT          (Execute approved tool via port)     │
  │          │                                             │
  │          ▼                                             │
  │   5. EVALUATE     (Assess progress & terminal status)  │
  │          │                                             │
  │          ▼                                             │
  │   6. UPDATE STATE (Persist state & log trace)          │
  └────────────────────────────────────────────────────────┘
```

---

## Core Domain Models

- **`AgentRun`**: Tracks `run_id`, `goal_id`, `user_id`, `status` (`PENDING`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`, `TIMEOUT`), `started_at`, `completed_at`, `current_step`, `iteration_count`, `error`, `steps`, and audit `trace`.
- **`AgentState`**: Working state snapshot (`goal_id`, `user_id`, `current_task_id`, `context`, `variables`, `last_observation`, `last_evaluation`, `is_terminal`).
- **`AgentStep`**: Detailed single-phase audit record (`step_number`, `phase`, `started_at`, `completed_at`, `input_state`, `decision`, `action_result`, `evaluation`, `output_state`, `error`).
- **`AgentDecision`**: Structured reasoning output (`decision_type`: `CALL_TOOL`, `FINISH`, `WAIT_USER`, `FAIL`; `tool_name`, `tool_args`, `reasoning`, `metadata`).

---

## Abstract Service Interfaces (Ports)

- **`StateRetrievalPort`**: Query domain state and persist state transitions.
- **`ToolExecutionPort`**: List approved tools and invoke tool executions abstractly.
- **`EvaluationPort`**: Assess action results and check progress toward goal completion.
- **`MemoryPort`**: Retrieve contextual memories and record step interaction traces.

---

## Generic Tool Execution Framework (Module 9)

Located in `lifethread_agent.tools`:
- **`ToolDefinition`**: Complete tool contract specifying name, description, Pydantic input schema, optional output schema, permission level, execution timeout, retry policy, and async handler.
- **`ToolRegistry`**: Central registry supporting programmatic (`register`) and decorator-based (`@registry.tool(...)`) tool declarations, permission filtering, and JSON schema export.
- **`ToolExecutor`**: Safe, resilient executor enforcing:
  - Input validation (Pydantic model validation).
  - Output validation (optional Pydantic model validation).
  - Permission checks (`ToolPermissionLevel`: `READ_ONLY`, `STANDARD`, `SENSITIVE`, `ADMIN`).
  - Timeout enforcement (`asyncio.timeout(tool.timeout)`).
  - Exponential backoff retries (`RetryPolicy`).
  - Cooperative cancellation (`CancellationToken`).
  - Standardized error codes (`ToolErrorCode`: `VALIDATION_ERROR`, `PERMISSION_DENIED`, `TIMEOUT_ERROR`, `EXECUTION_FAILED`, `TOOL_NOT_FOUND`, `CANCELLED`).
  - Normalized `ToolResult` containing execution duration and retry counts.
- **`GenericToolExecutionAdapter`**: Connects `ToolExecutor` directly into the agent runtime's `ToolExecutionPort`.

---

## Safety & Control Guards

- **Iteration Limit**: Enforces `max_iterations` to prevent runaway loops.
- **`LoopGuard`**: Computes decision signatures and prevents cyclic/infinite repetition loops.
- **`CancellationToken`**: Supports asynchronous cooperative cancellation across loop phases.
- **Timeouts**: Enforces both overall run timeouts (`max_run_seconds`) and individual step timeouts (`step_timeout_seconds`).
- **`AgentStateMachine`**: Strictly enforces legal lifecycle transitions.

