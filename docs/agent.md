# LifeThread Agent Orchestration & Cognitive Architecture

## 1. Overview

The LifeThread Agent Orchestrator governs the autonomous execution lifecycle of goals. It operates as an independent subsystem (`agent/` and `backend/app/services/`), strictly maintaining clean boundaries from underlying database implementations and external tool drivers.

```
       +-------------------------------------------------------------+
       |                  GOAL UNDERSTANDING ENGINE                  |
       |  Extracts core intent, domain categorization, criteria      |
       +------------------------------+------------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |                  GOAL DECOMPOSITION ENGINE                  |
       |  Generates hierarchical milestones, tasks, and DAG links   |
       +------------------------------+------------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |                  AUTONOMOUS PLANNING ENGINE                 |
       |  Allocates calendar slots, checks capacity, computes risk   |
       +------------------------------+------------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |                  AGENT EXECUTION RUNNER                     |
       |  Executes task queue; interfaces with MCP tool servers      |
       +------------------------------+------------------------------+
                                      |
                                      v
       +-------------------------------------------------------------+
       |                  EVALUATION & LEARNING SUITE                |
       |  Scores performance; detects weakness; stores memory       |
       +-------------------------------------------------------------+
```

---

## 2. Core Agent Modules

### 2.1 Goal Understanding (`GoalUnderstandingService`)
Transforms raw user input into an actionable goal schema:
1. **Title & Objective Synthesis:** Clarifies ambiguity into a measurable mission statement.
2. **Acceptance Criteria Extraction:** Produces verifiable conditions of satisfaction.
3. **Constraint Identification:** Discovers deadlines, time budgets, compliance requirements, or technological restrictions.
4. **Domain Tagging:** Identifies relevant domains (e.g. backend engineering, cloud security, machine learning) to seed semantic context retrieval.

### 2.2 Goal Decomposition (`GoalDecompositionService`)
Deconstructs a high-level goal into an executable Directed Acyclic Graph (DAG):
1. **Milestones:** Ordered phase boundaries that group tasks into logical checkpoints.
2. **Atomic Tasks:** Individual work units with realistic duration estimates (`estimated_minutes`).
3. **Dependency Edges:** Creates `BLOCKS` relationships between tasks where strict prerequisites exist.
4. **Critical Path Calculation:** Computes total serialized effort along the longest dependency chain.

### 2.3 Autonomous Planning (`PlanService`)
Transforms a set of tasks into a chronological schedule:
1. **Working Window Allocation:** Schedules tasks into discrete time blocks respecting working hours and daily capacity limits (e.g. 90 minutes per day on weekdays).
2. **Topological Order Sorting:** Ensures no task is scheduled before its prerequisite tasks complete.
3. **Deadline Risk Assessment:** Calculates the ratio of required effort to remaining available time ($0.0 \dots 1.0+$), assigning risk levels (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).

### 2.4 Agent Execution Engine (`AgentExecutionService`)
Dispatches tasks through an execution loop:
1. Validates prerequisites: verifies upstream tasks have reached `COMPLETED`.
2. Assembles context: queries `ContextEngine` and `SemanticMemoryRetriever` for relevant memories and user preferences.
3. Invokes MCP tools via the Model Context Protocol client.
4. Records execution telemetry and transitions task statuses.

---

## 3. Observability & Agent Traces (`AgentTraceService`)

Every autonomous agent run records structured events across 10 discrete stages with Chain-of-Thought (CoT) sanitization:

| Stage | Name | Description |
|---|---|---|
| **1** | `INPUT` | Trigger event, user prompt, and execution arguments |
| **2** | `SELECTED_CONTEXT` | Retrieved memories, preferences, and goal constraints |
| **3** | `PLANNED_ACTIONS` | Ordered execution steps and chosen strategies |
| **4** | `TOOL_CALLS` | MCP tool invocations with sanitized arguments |
| **5** | `TOOL_RESULTS` | Standardized tool outputs and error codes |
| **6** | `INTERNAL_STATE` | Intermediate agent variables and confidence metrics |
| **7** | `EVALUATION` | Real-time quality, feasibility, and risk assessments |
| **8** | `STATE_CHANGES` | Database updates committed to tasks, goals, or milestones |
| **9** | `REPLANNING_EVENT` | Trigger rationale, old vs new plan diff, and risk shifts |
| **10** | `FINAL_RESULT` | User-facing response payload and execution summary |

### CoT Defense Sanitization (`CoTSanitizer`)
To ensure safety and privacy:
- Internal reasoning tokens (e.g. `<thought>`, `<scratchpad>`) are scrubbed before reaching the frontend or logs.
- API keys, JWT tokens, and private credentials are automatically redacted with standard masks (`[REDACTED_SECRET]`).

---

## 4. Evaluation Suite (`AgentEvaluationSuite`)

The evaluation engine assesses agent execution across 4 core dimensions:
1. **Completeness Score (0.0 to 1.0):** Proportion of required acceptance criteria satisfied.
2. **Feasibility Score (0.0 to 1.0):** Adherence to calendar time and capacity constraints.
3. **Constraint Adherence (0.0 to 1.0):** Verification that no policy, budget, or tool constraint was violated.
4. **Recovery Efficacy (0.0 to 1.0):** Speed and accuracy of self-healing following a task failure.
