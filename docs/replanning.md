# LifeThread Autonomous Replanning Engine

## 1. Overview

In long-running goal execution, assumptions inevitably fail: external deadlines move forward, daily working capacity shrinks, tasks fail due to unforeseen environmental bugs, or dependencies become blocked. 

The LifeThread Autonomous Replanning Engine detects these triggers, performs non-destructive impact analysis, and generates a new plan revision with an explainable diff.

```
+---------------------------------------------------------------------------------------+
|                                  REPLANNING TRIGGERS                                  |
|   1. Compressed Deadline    2. Time Budget Cut    3. Task Failure / Exception         |
|   4. Newly Discovered Weakness                    5. Blocked Prerequisite Task        |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                    IMPACT ANALYSIS                                    |
|   POST /api/v1/replanning/preview: Computes schedule feasibility & shifts             |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                              EXPLAINABLE REPLANNING DIFF                              |
|   { added_tasks: [...], removed_tasks: [...], rescheduled_tasks: [...], risk_shift }  |
+-------------------------------------------+-------------------------------------------+
                                            |
                                            v
+---------------------------------------------------------------------------------------+
|                                 NEW PLAN COMMITMENT                                   |
|   Plan v1 (SUPERSEDED) ──────────────> Plan v2 (ACTIVE) with audited rationale        |
+---------------------------------------------------------------------------------------+
```

---

## 2. Trigger Conditions & Handlers

### 2.1 Changing Deadlines
- **Scenario:** An external party or user accelerates a deadline (e.g. SOC2 compliance audit advanced from Day 30 to Day 12).
- **Behavior:** The scheduler compacts available slots, increases daily utilization, and elevates deadline risk (e.g. 0.15 LOW → 0.78 HIGH). If mathematically impossible within constraints, the engine marks the plan infeasible and suggests scope reductions.

### 2.2 Limited Available Time
- **Scenario:** The user reduces working capacity (e.g. from 4 hours to 90 minutes per day).
- **Behavior:** Tasks exceeding the new daily budget are flagged for sub-decomposition. Remaining tasks are partitioned across subsequent business days without calendar slot overlap.

### 2.3 Task Failure & Recovery Loop
- **Scenario:** A task encounters an unrecoverable exception (e.g. database socket timeout or network disconnection).
- **Behavior:** The failed task is transitioned to `CANCELLED`/`FAILED`. The replanning engine inserts a targeted recovery task (e.g. *"Rollback Kafka Consumer Group & Apply Schema Evolution Patch"*), links prerequisite dependencies, and reschedules downstream tasks.

### 2.4 Newly Discovered Weakness (Continuous Learning)
- **Scenario:** The evaluation suite detects recurrent struggles with a specific topic (e.g. Rust Tokio pin projection).
- **Behavior:** A `SEMANTIC` memory ("Learned weakness") is created with a 1536-dim vector embedding. The replanning engine inserts a targeted remedial drill task into the plan queue before the next major milestone.

### 2.5 Blocked Dependencies
- **Scenario:** A prerequisite task takes longer than expected, delaying dependent tasks linked via `TaskDependency(dependency_type="BLOCKS")`.
- **Behavior:** Downstream tasks are marked `BLOCKED`. The scheduler reschedules the blocked tasks forward in time starting immediately after the anticipated new completion timestamp of the blocker.

---

## 3. Plan Versioning & Explainable Diffs

### 3.1 Multi-Version Plan State
- Each plan revision is assigned a sequential version number (`Plan.version = 1, 2, ...`).
- When Plan $N+1$ is committed:
  - Plan $N$ transitions to `PlanStatus.SUPERSEDED`.
  - Plan $N+1$ transitions to `PlanStatus.ACTIVE`.
  - All existing historical records and rationales remain intact for audits and rollback.

### 3.2 Structure of `diff_summary`
The plan metadata records a structured diff explaining the change:
```json
{
  "reason": "Auditor advanced deadline from 30 days to 12 days",
  "trigger": "deadline_compression",
  "previous_version": 1,
  "new_version": 2,
  "diff_summary": {
    "added_tasks_count": 0,
    "rescheduled_tasks_count": 3,
    "reprioritized_tasks_count": 2,
    "deadline_risk_delta": 0.63,
    "previous_risk_level": "LOW",
    "new_risk_level": "HIGH"
  }
}
```

---

## 4. Reversible Rollback Protocol

If a proposed replan is rejected by the user or an automated supervisor:
1. `POST /api/v1/replanning/rollback` is invoked with the target goal ID and version.
2. The current `ACTIVE` plan is marked `ABANDONED`.
3. The specified previous plan is restored to `ACTIVE`.
4. The timeline and task execution queues immediately realign to the restored state.
