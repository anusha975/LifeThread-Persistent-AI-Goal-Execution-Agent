# LifeThread Memory System

## 1. Overview

The LifeThread Memory System provides persistent, multi-tenant memory for the autonomous agent. Instead of relying solely on transient conversational state, LifeThread preserves learnings, past outcomes, strategic constraints, and user preferences across unbounded time horizons.

---

## 2. The 4 Canonical Memory Types

```
                                  +------------------+
                                  |   MEMORY ENGINE  |
                                  +--------+---------+
                                           |
         +--------------------+------------+------------+--------------------+
         |                    |                         |                    |
         v                    v                         v                    v
  +--------------+     +--------------+          +--------------+     +--------------+
  |   EPISODIC   |     |   SEMANTIC   |          |     GOAL     |     |  PREFERENCE  |
  +--------------+     +--------------+          +--------------+     +--------------+
  | Past task    |     | General      |          | Strategic    |     | User habits, |
  | execution    |     | knowledge,   |          | policies,    |     | formats,     |
  | outcomes,    |     | strengths,   |          | immutable    |     | cadence,     |
  | failures,    |     | weaknesses,  |          | constraints, |     | communication|
  | milestones   |     | principles   |          | criteria     |     | style        |
  +--------------+     +--------------+          +--------------+     +--------------+
```

### 2.1 `EPISODIC` Memory
- **Purpose:** Captures specific autobiographical execution events and concrete task outcomes.
- **Example:** *"Task 'Configure Istio Ingress Gateway' failed with certificate socket timeout; recovered via chunked throttling."*
- **Origin:** Generated automatically by the agent execution runner or error recovery handler.

### 2.2 `SEMANTIC` Memory
- **Purpose:** Captures timeless concepts, learned rules, domain understanding, and detected user/system weaknesses.
- **Example:** *"Operator exhibits difficulty with Rust async lifetime bounds and pin projection in multi-threaded Tokio actors."*
- **Origin:** Synthesized by the evaluation suite and continuous learning loop upon detecting repeated patterns.

### 2.3 `GOAL` Memory
- **Purpose:** Captures strategic invariants, organizational policies, and immutable boundary conditions for active goals.
- **Example:** *"External auditor advanced SOC2 evidence deadline from 30 days to 12 days, requiring aggressive replanning."*
- **Origin:** Extracted during Goal Understanding or registered after major replanning triggers.

### 2.4 `PREFERENCE` Memory
- **Purpose:** Captures user working style, preferred output formats, schedule preferences, and notification tolerances.
- **Example:** *"Operator prefers learning via isolated minimal code reproduction examples rather than large monolithic repos."*
- **Origin:** Captured from explicit user configuration or inferred from recurring user interaction feedback.

---

## 3. Memory Lifecycle & Operations

### 3.1 Deduplication & Reinforcement Engine (`MemoryService.detect_duplicate`)
To prevent memory bloat and duplicate entries:
1. When a new memory candidate arrives, normalized text comparison searches for existing matching memories within the same user space and memory type.
2. If an existing record matches:
   - `access_count` increments by 1.
   - `importance_score` is reinforced to the maximum of existing and new values.
   - `confidence` increases by `+0.05` (capped at 1.0).
   - `last_accessed_at` is updated to current UTC time.
   - Metadata is merged with a `last_reinforced_at` timestamp.
3. If no match exists, a new record is persisted.

### 3.2 Importance Scoring & Confidence
- **Importance Score ($0.0 \dots 1.0$):** Reflects the criticality of the memory. Critical errors and fundamental constraints are assigned $0.85 \dots 1.0$; minor cosmetic preferences are assigned $0.4 \dots 0.6$.
- **Confidence ($0.0 \dots 1.0$):** Measures the certainty of the observation. Direct execution outcomes carry $1.0$; inferred hypotheses start at $0.7 \dots 0.85$ and grow via reinforcement.

### 3.3 Security & Multi-Tenant Audit Logging
All memory mutations produce security audit records:
- `MEMORY_STORED`: Emitted upon creating a new memory record.
- `MEMORY_REINFORCED_DUPLICATE`: Emitted when an existing memory is reinforced.
- `MEMORY_UPDATED`: Emitted upon explicit content or metadata edit.
- `MEMORY_DELETED`: Emitted upon user deletion.
- Every operation checks and strictly enforces `user_id` authorization.
