"""LifeThread Demo Scenarios Definition.

Module 46: Demo Data and Example Scenarios.

This module defines 6 realistic long-running goal scenarios:
1. Changing Deadlines (SOC2 Type II Compliance)
2. Limited Available Time (Real-Time Financial Ledger in Go)
3. Task Failure & Recovery (Zero-Downtime Database Migration)
4. Newly Discovered Weakness (Advanced Rust Systems Programming)
5. Blocked Dependency (Multi-Region Zero-Trust Service Mesh)
6. Successful Completion (pgvector Semantic RAG Vector Engine)

All scenario entities are cleanly separated from production logic.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

DEMO_USER_EMAIL = "demo@lifethread.ai"
DEMO_USER_NAME = "Alex Rivera (Demo Operator)"
DEMO_USER_PASSWORD = "DemoPassword123!"

NOW = datetime.now(UTC)


def get_demo_scenarios_data(now: datetime | None = None) -> list[dict[str, Any]]:
    """Return structured definitions for all 6 demo scenarios."""
    base_time = now or datetime.now(UTC)

    return [
        # =====================================================================
        # SCENARIO 1: CHANGING DEADLINES (SOC2 Type II Compliance)
        # Demonstrates: compressed deadline, multi-version plan, replanning diff,
        # elevated deadline risk (LOW -> HIGH).
        # =====================================================================
        {
            "id": "scenario_1_changing_deadlines",
            "scenario_name": "Changing Deadlines",
            "title": "Enterprise SOC2 Type II Security Compliance & Certification",
            "objective": "Complete trust service criteria audit, implement access controls, and achieve certified SOC2 Type II compliance.",
            "description": (
                "Multi-month organizational security audit encompassing AWS infrastructure access controls, "
                "continuous evidence collection, and independent third-party auditor verification."
            ),
            "priority": "CRITICAL",
            "status": "ACTIVE",
            # Initial deadline was +30 days, auditor compressed it to +12 days
            "deadline": base_time + timedelta(days=12),
            "success_criteria": [
                "100% of AWS IAM users enforced with hardware MFA",
                "Automated nightly vulnerability scanning with zero critical findings",
                "Clean auditor opinion with zero qualification exceptions",
            ],
            "constraints": [
                {
                    "type": "deadline_compression",
                    "value": "External auditor advanced audit window from 30 days to 12 days",
                    "metadata": {"original_deadline_days": 30, "revised_deadline_days": 12, "compressed": True},
                },
                {
                    "type": "compliance_standard",
                    "value": "AICPA Trust Services Criteria (Security, Confidentiality)",
                    "metadata": {"standard": "SOC2_TYPE_II"},
                },
            ],
            "milestones": [
                {
                    "title": "Trust Service Criteria Gap Analysis",
                    "description": "Baseline assessment against AICPA security and confidentiality criteria.",
                    "status": "COMPLETED",
                    "order_index": 1,
                    "deadline": base_time - timedelta(days=5),
                },
                {
                    "title": "Access Control Policies & MFA Remediation",
                    "description": "Enforce hardware MFA, eliminate static root credentials, and automate rotation.",
                    "status": "IN_PROGRESS",
                    "order_index": 2,
                    "deadline": base_time + timedelta(days=4),
                },
                {
                    "title": "External Auditor Evidence Collection",
                    "description": "Export automated configuration snapshots and host auditor onsite walkthrough.",
                    "status": "PENDING",
                    "order_index": 3,
                    "deadline": base_time + timedelta(days=12),
                },
            ],
            "tasks": [
                {
                    "title": "Audit AWS IAM roles and enforce hardware security keys",
                    "description": "Scan AWS Organization accounts for root access and enforce FIDO2 WebAuthn keys.",
                    "status": "COMPLETED",
                    "priority": "CRITICAL",
                    "estimated_minutes": 120,
                    "due_at": base_time - timedelta(days=2),
                    "completed_at": base_time - timedelta(days=2),
                    "milestone_index": 0,
                },
                {
                    "title": "Implement automated weekly vendor SOC2 report review log",
                    "description": "Review and record compliance status for third-party cloud sub-processors.",
                    "status": "IN_PROGRESS",
                    "priority": "HIGH",
                    "estimated_minutes": 90,
                    "due_at": base_time + timedelta(days=3),
                    "completed_at": None,
                    "milestone_index": 1,
                },
                {
                    "title": "Synthesize continuous evidence exports for external auditor portal",
                    "description": "Package AWS CloudTrail, KMS key rotation, and GitHub branch protection logs into audit zip.",
                    "status": "PENDING",
                    "priority": "CRITICAL",
                    "estimated_minutes": 180,
                    "due_at": base_time + timedelta(days=10),
                    "completed_at": None,
                    "milestone_index": 2,
                },
            ],
            "plans": [
                # Plan Version 1 (Generated before deadline compression)
                {
                    "version": 1,
                    "status": "SUPERSEDED",
                    "is_feasible": True,
                    "deadline_risk": 0.15,
                    "risk_level": "LOW",
                    "schedule_utilization": 0.45,
                    "reason": "Initial baseline schedule with comfortable 30-day auditor window.",
                    "generated_at": base_time - timedelta(days=6),
                },
                # Plan Version 2 (Triggered by deadline compression)
                {
                    "version": 2,
                    "status": "ACTIVE",
                    "is_feasible": True,
                    "deadline_risk": 0.78,
                    "risk_level": "HIGH",
                    "schedule_utilization": 0.85,
                    "reason": (
                        "External auditor compressed evidence delivery date from Day 30 to Day 12. "
                        "Replanned critical path: elevated IAM tasks to CRITICAL and shifted vendor reviews forward."
                    ),
                    "generated_at": base_time - timedelta(days=1),
                },
            ],
            "memories": [
                {
                    "memory_type": "GOAL",
                    "content": "External auditor advanced SOC2 evidence deadline from 30 days to 12 days, requiring aggressive replanning.",
                    "importance_score": 0.95,
                    "confidence": 1.0,
                    "source": "replanning_event",
                    "metadata": {"category": "Goal memory", "impact": "deadline_compression", "urgency": "high"},
                }
            ],
            "agent_runs": [
                {
                    "trigger": "deadline_changed",
                    "summary": "Impact analysis & dynamic replanning following auditor deadline acceleration",
                    "status": "SUCCESS",
                    "duration_ms": 340,
                    "events": [
                        {
                            "event_type": "AGENT_RUN",
                            "status": "SUCCESS",
                            "description": "Triggered replanning pipeline after external deadline compressed to 12 days",
                        },
                        {
                            "event_type": "DECISION",
                            "status": "SUCCESS",
                            "description": "Identified critical path acceleration: compressed gap between Task 1 and Task 3.",
                        },
                        {
                            "event_type": "EVALUATION",
                            "status": "SUCCESS",
                            "description": "Recalculated deadline risk: shifted from 0.15 (LOW) to 0.78 (HIGH).",
                        },
                        {
                            "event_type": "STATE_UPDATE",
                            "status": "SUCCESS",
                            "description": "Committed Plan v2 with revised work windows and updated task priority rankings.",
                        },
                    ],
                }
            ],
        },

        # =====================================================================
        # SCENARIO 2: LIMITED AVAILABLE TIME (Financial Ledger in Go)
        # Demonstrates: capacity constraint (90 min/day), deterministic scheduling,
        # slot distribution over weekdays.
        # =====================================================================
        {
            "id": "scenario_2_limited_available_time",
            "scenario_name": "Limited Available Time",
            "title": "Architect Real-Time Financial Ledger Microservice in Go",
            "objective": "Build double-entry immutable ledger engine with gRPC interface under strict 90-minute daily working capacity.",
            "description": (
                "Develop high-performance transactional accounting engine with strict idempotency and cryptographic audit hashing. "
                "Execution must strictly honor user's 90-minute daily deep-work capacity limit."
            ),
            "priority": "HIGH",
            "status": "ACTIVE",
            "deadline": base_time + timedelta(days=21),
            "success_criteria": [
                "Zero fractional cent balance discrepancy across concurrent multi-currency postings",
                "Idempotent gRPC request deduplication within 5ms response window",
                "10,000 transactions/second sustained throughput in mock load testing",
            ],
            "constraints": [
                {
                    "type": "capacity_constraint",
                    "value": "90 minutes maximum deep-work allocation per day on weekdays only",
                    "metadata": {"daily_budget_minutes": 90, "days": ["mon", "tue", "wed", "thu", "fri"]},
                }
            ],
            "milestones": [
                {
                    "title": "Core Accounting State Machine",
                    "description": "Double-entry rules, debit/credit invariant validation.",
                    "status": "COMPLETED",
                    "order_index": 1,
                    "deadline": base_time - timedelta(days=2),
                },
                {
                    "title": "Transactional Idempotency & WAL",
                    "description": "Write-ahead logging and Redis distributed locking.",
                    "status": "IN_PROGRESS",
                    "order_index": 2,
                    "deadline": base_time + timedelta(days=8),
                },
                {
                    "title": "gRPC Ingress & Load Benchmarks",
                    "description": "Protobuf contract and high-concurrency performance validation.",
                    "status": "PENDING",
                    "order_index": 3,
                    "deadline": base_time + timedelta(days=21),
                },
            ],
            "tasks": [
                {
                    "title": "Define account schemas & ledger transaction journal",
                    "description": "Write Go structs, database DDL, and debit/credit balanced sum assertions.",
                    "status": "COMPLETED",
                    "priority": "HIGH",
                    "estimated_minutes": 90,
                    "due_at": base_time - timedelta(days=3),
                    "completed_at": base_time - timedelta(days=3),
                    "milestone_index": 0,
                },
                {
                    "title": "Implement idempotency lock via Redis distributed mutex",
                    "description": "Guard concurrent transaction mutations with unique request fingerprint keys.",
                    "status": "IN_PROGRESS",
                    "priority": "HIGH",
                    "estimated_minutes": 90,
                    "due_at": base_time + timedelta(days=1),
                    "completed_at": None,
                    "milestone_index": 1,
                },
                {
                    "title": "Build gRPC handlers and protocol buffer definitions",
                    "description": "Expose PostTransaction and GetAccountBalance endpoints with structured error codes.",
                    "status": "PENDING",
                    "priority": "MEDIUM",
                    "estimated_minutes": 90,
                    "due_at": base_time + timedelta(days=4),
                    "completed_at": None,
                    "milestone_index": 2,
                },
                {
                    "title": "Run concurrent debit/credit load test (10k ops/sec)",
                    "description": "Simulate 50 parallel bank accounts transferring random sums to assert zero balance drift.",
                    "status": "PENDING",
                    "priority": "MEDIUM",
                    "estimated_minutes": 90,
                    "due_at": base_time + timedelta(days=7),
                    "completed_at": None,
                    "milestone_index": 2,
                },
            ],
            "plans": [
                {
                    "version": 1,
                    "status": "ACTIVE",
                    "is_feasible": True,
                    "deadline_risk": 0.22,
                    "risk_level": "LOW",
                    "schedule_utilization": 0.65,
                    "reason": "Capacity-aware schedule allocating exactly 1 task (90 min) per workday morning.",
                    "generated_at": base_time - timedelta(days=4),
                }
            ],
            "memories": [
                {
                    "memory_type": "PREFERENCE",
                    "content": "Operator has strict limited working capacity of 90 minutes/day on weekdays for deep coding sessions.",
                    "importance_score": 0.90,
                    "confidence": 1.0,
                    "source": "user_profile",
                    "metadata": {"category": "Preference", "focus_duration": "90m", "schedule_window": "morning"},
                }
            ],
            "agent_runs": [
                {
                    "trigger": "capacity_scheduling",
                    "summary": "Deterministic scheduling respecting daily 90-minute capacity budget",
                    "status": "SUCCESS",
                    "duration_ms": 280,
                    "events": [
                        {
                            "event_type": "AGENT_RUN",
                            "status": "SUCCESS",
                            "description": "Loaded user capacity constraint: 90 minutes max daily allocation.",
                        },
                        {
                            "event_type": "DECISION",
                            "status": "SUCCESS",
                            "description": "Partitioned 360 total estimated minutes into 4 discrete 90-minute daily work blocks.",
                        },
                        {
                            "event_type": "STATE_UPDATE",
                            "status": "SUCCESS",
                            "description": "Committed calendar slots ensuring zero overlapping or budget overflow.",
                        },
                    ],
                }
            ],
        },

        # =====================================================================
        # SCENARIO 3: TASK FAILURE & DIAGNOSTIC RECOVERY (Database Migration)
        # Demonstrates: task failure (FAILED status), agent diagnostic trace,
        # automated recovery loop, and safe operator notification.
        # =====================================================================
        {
            "id": "scenario_3_task_failure",
            "scenario_name": "Task Failure & Recovery",
            "title": "Zero-Downtime Distributed Database Migration & Partitioning",
            "objective": "Migrate multi-terabyte transactional database to Aurora PostgreSQL with zero write interruption.",
            "description": (
                "Execute live data migration using logical replication streams. Validates error handling, "
                "safe failure recovery, diagnostic logging, and retry strategies under network latency spikes."
            ),
            "priority": "HIGH",
            "status": "ACTIVE",
            "deadline": base_time + timedelta(days=16),
            "success_criteria": [
                "Continuous replication lag held under 1.5 seconds during peak traffic",
                "Automated rollback triggered if replica divergence exceeds 0.01%",
                "Zero data loss during final cutover phase",
            ],
            "constraints": [
                {
                    "type": "sla",
                    "value": "Zero write downtime (< 5 seconds switchover window)",
                    "metadata": {"max_downtime_seconds": 5},
                }
            ],
            "milestones": [
                {
                    "title": "Pre-migration Replica Synchronization",
                    "description": "Establish baseline replication slot and monitor read lag.",
                    "status": "COMPLETED",
                    "order_index": 1,
                    "deadline": base_time - timedelta(days=3),
                },
                {
                    "title": "Logical Replication Stream Cutover",
                    "description": "Stream transactional updates with automated conflict resolution.",
                    "status": "IN_PROGRESS",
                    "order_index": 2,
                    "deadline": base_time + timedelta(days=5),
                },
                {
                    "title": "Application Connection Pool Reroute",
                    "description": "Drain legacy pool and switch DNS endpoints to Aurora target.",
                    "status": "PENDING",
                    "order_index": 3,
                    "deadline": base_time + timedelta(days=16),
                },
            ],
            "tasks": [
                {
                    "title": "Validate replica read lag and pg_stat_replication",
                    "description": "Verify replication stream is active and within acceptable 500ms latency envelope.",
                    "status": "COMPLETED",
                    "priority": "HIGH",
                    "estimated_minutes": 45,
                    "due_at": base_time - timedelta(days=2),
                    "completed_at": base_time - timedelta(days=2),
                    "milestone_index": 0,
                },
                {
                    "title": "Initialize continuous pglogical replication stream",
                    "description": "Execute schema copy and stream live logical replication batches.",
                    "status": "CANCELLED",  # Represents task failure/interruption undergoing diagnostic recovery
                    "priority": "CRITICAL",
                    "estimated_minutes": 120,
                    "due_at": base_time + timedelta(days=1),
                    "completed_at": None,
                    "milestone_index": 1,
                },
                {
                    "title": "Execute automated schema parity check across all tables",
                    "description": "Run checksum queries on row counts and foreign key constraints between primary and target.",
                    "status": "PENDING",
                    "priority": "HIGH",
                    "estimated_minutes": 60,
                    "due_at": base_time + timedelta(days=6),
                    "completed_at": None,
                    "milestone_index": 2,
                },
            ],
            "plans": [
                {
                    "version": 1,
                    "status": "ACTIVE",
                    "is_feasible": True,
                    "deadline_risk": 0.40,
                    "risk_level": "MEDIUM",
                    "schedule_utilization": 0.70,
                    "reason": "Active migration schedule accounting for replication warmup and validation.",
                    "generated_at": base_time - timedelta(days=3),
                }
            ],
            "memories": [
                {
                    "memory_type": "EPISODIC",
                    "content": "Task 'Initialize continuous pglogical replication stream' failed with IOPS saturation; recovered via chunked throttling.",
                    "importance_score": 0.88,
                    "confidence": 0.95,
                    "source": "agent_error_handler",
                    "metadata": {"category": "Past outcome", "error": "IOPS_TIMEOUT", "recovery": "chunk_throttling"},
                }
            ],
            "agent_runs": [
                {
                    "trigger": "task_failure_recovery",
                    "summary": "Automated diagnostic & tool recovery following database replication socket timeout",
                    "status": "SUCCESS",
                    "duration_ms": 620,
                    "events": [
                        {
                            "event_type": "AGENT_RUN",
                            "status": "RUNNING",
                            "description": "Triggered by failure exception on task 'Initialize continuous pglogical replication stream'",
                        },
                        {
                            "event_type": "DECISION",
                            "status": "SUCCESS",
                            "description": "Detected socket read timeout. Analyzing pg_stat_activity and disk IOPS metrics.",
                        },
                        {
                            "event_type": "TOOL_CALL",
                            "status": "SUCCESS",
                            "description": "Invoked mcp__database_diagnostic with arguments: check_iops=True, stream_id='pglogical_aurora'",
                        },
                        {
                            "event_type": "TOOL_RESULT",
                            "status": "SUCCESS",
                            "description": "Diagnostic result: Storage volume IOPS saturated at 3,000 IOPS; replication socket timed out.",
                        },
                        {
                            "event_type": "EVALUATION",
                            "status": "SUCCESS",
                            "description": "Safety evaluation: Approved automated retry with batch rate limited to 500 rows/sec.",
                        },
                        {
                            "event_type": "STATE_UPDATE",
                            "status": "SUCCESS",
                            "description": "Task status reset to PENDING with chunked throttle parameters applied.",
                        },
                    ],
                }
            ],
        },

        # =====================================================================
        # SCENARIO 4: NEWLY DISCOVERED WEAKNESS (Rust Systems Programming)
        # Demonstrates: continuous learning loop, weakness memory vector,
        # tailored remedial task insertion, and preference modeling.
        # =====================================================================
        {
            "id": "scenario_4_newly_discovered_weakness",
            "scenario_name": "Newly Discovered Weakness",
            "title": "Master Advanced Rust Systems Programming & Async Tokio",
            "objective": "Master memory safety guarantees, async Tokio internals, pin projection, and unmanaged FFI integration.",
            "description": (
                "Deep curriculum in advanced systems programming in Rust. Demonstrates continuous learning loop: "
                "agent detects conceptual struggles during task execution and adapts curriculum."
            ),
            "priority": "MEDIUM",
            "status": "ACTIVE",
            "deadline": base_time + timedelta(days=45),
            "success_criteria": [
                "Write zero-copy packet parser with lifetime annotations passing Miri verification",
                "Implement custom Tokio Stream with Pin & Unpin projection",
                "Integrate C shared library via safe FFI wrapper",
            ],
            "constraints": [
                {
                    "type": "pedagogical",
                    "value": "Hands-on implementation drills preferred over theoretical documentation",
                    "metadata": {"style": "drill_exercises"},
                }
            ],
            "milestones": [
                {
                    "title": "Ownership, Borrow Checker, and Lifetimes",
                    "description": "Master non-lexical lifetimes, variance, and interior mutability.",
                    "status": "COMPLETED",
                    "order_index": 1,
                    "deadline": base_time - timedelta(days=10),
                },
                {
                    "title": "Async Runtime, Tokio, and Pin Projection",
                    "description": "Understand Future contract, Waker mechanics, and self-referential structs.",
                    "status": "IN_PROGRESS",
                    "order_index": 2,
                    "deadline": base_time + timedelta(days=14),
                },
                {
                    "title": "C FFI and Unsafe Rust Optimization",
                    "description": "Bindgen, ABI compatibility, and memory layout verification.",
                    "status": "PENDING",
                    "order_index": 3,
                    "deadline": base_time + timedelta(days=45),
                },
            ],
            "tasks": [
                {
                    "title": "Implement intrusive linked list with custom Drop semantics",
                    "description": "Write safe wrapper around raw pointers with custom lifetime guarantees.",
                    "status": "COMPLETED",
                    "priority": "MEDIUM",
                    "estimated_minutes": 120,
                    "due_at": base_time - timedelta(days=12),
                    "completed_at": base_time - timedelta(days=12),
                    "milestone_index": 0,
                },
                {
                    "title": "Drill Exercise: Pin projection and custom Future polling in Tokio",
                    "description": (
                        "Targeted remedial drill inserted after agent diagnosed weakness in async lifetime bounds: "
                        "implement custom DelayFuture without pin_project macro."
                    ),
                    "status": "IN_PROGRESS",
                    "priority": "HIGH",
                    "estimated_minutes": 90,
                    "due_at": base_time + timedelta(days=2),
                    "completed_at": None,
                    "milestone_index": 1,
                },
                {
                    "title": "Build multi-threaded actor mailbox using tokio::sync::mpsc",
                    "description": "Handle backpressure, select! polling, and clean cancellation tokens.",
                    "status": "PENDING",
                    "priority": "MEDIUM",
                    "estimated_minutes": 90,
                    "due_at": base_time + timedelta(days=8),
                    "completed_at": None,
                    "milestone_index": 1,
                },
            ],
            "plans": [
                {
                    "version": 1,
                    "status": "ACTIVE",
                    "is_feasible": True,
                    "deadline_risk": 0.28,
                    "risk_level": "LOW",
                    "schedule_utilization": 0.50,
                    "reason": "Adapted curriculum inserting focused drill exercise on Pin projection.",
                    "generated_at": base_time - timedelta(days=8),
                }
            ],
            "memories": [
                {
                    "memory_type": "SEMANTIC",
                    "content": "Operator exhibits difficulty with Rust async lifetime bounds and pin projection in multi-threaded Tokio actors.",
                    "importance_score": 0.92,
                    "confidence": 0.94,
                    "source": "agent_evaluation",
                    "metadata": {
                        "category": "Learned weakness",
                        "concept": "pin_projection",
                        "adaptive_action": "insert_drill_exercises",
                        "domain": "rust_systems",
                    },
                },
                {
                    "memory_type": "PREFERENCE",
                    "content": "Operator prefers learning via isolated minimal code reproduction examples rather than large monolithic repos.",
                    "importance_score": 0.85,
                    "confidence": 1.0,
                    "source": "user_profile",
                    "metadata": {"category": "Preference", "format": "minimal_repro"},
                },
            ],
            "agent_runs": [
                {
                    "trigger": "evaluation_reflection",
                    "summary": "Learning loop diagnosed weakness in async pin projection; synthesized remedial drill",
                    "status": "SUCCESS",
                    "duration_ms": 410,
                    "events": [
                        {
                            "event_type": "AGENT_RUN",
                            "status": "SUCCESS",
                            "description": "Triggered by task review of 'Async Runtime, Tokio, and Pin Projection'",
                        },
                        {
                            "event_type": "EVALUATION",
                            "status": "SUCCESS",
                            "description": "Identified recurring compilation errors on Pin<&mut Self> borrow lifetime bounds.",
                        },
                        {
                            "event_type": "DECISION",
                            "status": "SUCCESS",
                            "description": "Synthesized new memory 'Learned weakness' and scheduled targeted drill task.",
                        },
                        {
                            "event_type": "STATE_UPDATE",
                            "status": "SUCCESS",
                            "description": "Persisted learned weakness memory and inserted drill task into plan queue.",
                        },
                    ],
                }
            ],
        },

        # =====================================================================
        # SCENARIO 5: BLOCKED DEPENDENCY (Service Mesh Deployment)
        # Demonstrates: directed acyclic graph (DAG), BLOCKS dependency edge,
        # BLOCKED task status, prerequisite validation.
        # =====================================================================
        {
            "id": "scenario_5_blocked_dependency",
            "scenario_name": "Blocked Dependency",
            "title": "Multi-Region Zero-Trust Service Mesh Deployment",
            "objective": "Deploy Istio service mesh with mTLS encryption and traffic routing across us-east-1 and eu-west-1.",
            "description": (
                "Establish mutual TLS zero-trust network boundaries across multiple Kubernetes clusters. "
                "Demonstrates dependency constraints: downstream gateway setup is strictly blocked by upstream certificate generation."
            ),
            "priority": "HIGH",
            "status": "ACTIVE",
            "deadline": base_time + timedelta(days=25),
            "success_criteria": [
                "100% of inter-service RPCs encrypted with verified SPIFFE/SPIRE x509 certificates",
                "Automated cert-manager rotation with zero traffic drops",
                "Canary traffic routing verified across transatlantic clusters",
            ],
            "constraints": [
                {
                    "type": "security_policy",
                    "value": "mTLS mandatory; plaintext HTTP connections rejected at ingress",
                    "metadata": {"policy": "ENFORCE_MTLS"},
                }
            ],
            "milestones": [
                {
                    "title": "Infrastructure TLS Certificates",
                    "description": "Generate Root CA and intermediate signing certs in Cloudflare & AWS Secrets Manager.",
                    "status": "IN_PROGRESS",
                    "order_index": 1,
                    "deadline": base_time + timedelta(days=3),
                },
                {
                    "title": "Control Plane & Ingress Gateway Setup",
                    "description": "Deploy Istiod and configure mTLS ingress gateways.",
                    "status": "PENDING",
                    "order_index": 2,
                    "deadline": base_time + timedelta(days=12),
                },
                {
                    "title": "Canary Traffic Verification",
                    "description": "Validate cross-region routing with synthetic traffic generator.",
                    "status": "PENDING",
                    "order_index": 3,
                    "deadline": base_time + timedelta(days=25),
                },
            ],
            "tasks": [
                {
                    "title": "Provision Cloudflare edge mTLS Root CA & Intermediate Certs",
                    "description": "Generate high-entropy RSA-4096 signing root and sync intermediate bundle to cluster secrets.",
                    "status": "IN_PROGRESS",
                    "priority": "CRITICAL",
                    "estimated_minutes": 90,
                    "due_at": base_time + timedelta(days=2),
                    "completed_at": None,
                    "milestone_index": 0,
                },
                {
                    "title": "Configure Istio Ingress Gateway with mTLS Client Validation",
                    "description": (
                        "Mount intermediate certificates and configure STRICT mTLS PeerAuthentication. "
                        "BLOCKED: cannot proceed until Cloudflare edge mTLS Root CA is provisioned."
                    ),
                    "status": "BLOCKED",
                    "priority": "HIGH",
                    "estimated_minutes": 120,
                    "due_at": base_time + timedelta(days=6),
                    "completed_at": None,
                    "milestone_index": 1,
                    "blocked_by_task_index": 0,  # depends on task 0
                },
                {
                    "title": "Run synthetic canary traffic across East/West clusters",
                    "description": "Inject 500 requests/sec across regions to verify mTLS handshake latency < 2ms.",
                    "status": "PENDING",
                    "priority": "MEDIUM",
                    "estimated_minutes": 60,
                    "due_at": base_time + timedelta(days=15),
                    "completed_at": None,
                    "milestone_index": 2,
                    "blocked_by_task_index": 1,  # depends on task 1
                },
            ],
            "plans": [
                {
                    "version": 1,
                    "status": "ACTIVE",
                    "is_feasible": True,
                    "deadline_risk": 0.35,
                    "risk_level": "MEDIUM",
                    "schedule_utilization": 0.60,
                    "reason": "Topological schedule respecting strict prerequisite certificate dependency.",
                    "generated_at": base_time - timedelta(days=2),
                }
            ],
            "memories": [
                {
                    "memory_type": "GOAL",
                    "content": "Istio ingress configuration requires pre-existing Cloudflare mTLS certificates to avoid deployment pod crash loops.",
                    "importance_score": 0.82,
                    "confidence": 1.0,
                    "source": "dependency_analysis",
                    "metadata": {"category": "Goal memory", "dependency_prerequisite": "certificates"},
                }
            ],
            "agent_runs": [
                {
                    "trigger": "dependency_dag_evaluation",
                    "summary": "Validated DAG topological ordering; enforced BLOCKED status on downstream gateway task",
                    "status": "SUCCESS",
                    "duration_ms": 190,
                    "events": [
                        {
                            "event_type": "AGENT_RUN",
                            "status": "SUCCESS",
                            "description": "Evaluated DAG dependency chain for 'Multi-Region Zero-Trust Service Mesh'",
                        },
                        {
                            "event_type": "DECISION",
                            "status": "SUCCESS",
                            "description": "Task 'Configure Istio Ingress Gateway' has unfulfilled prerequisite 'Provision Cloudflare edge mTLS Root CA'.",
                        },
                        {
                            "event_type": "STATE_UPDATE",
                            "status": "SUCCESS",
                            "description": "Enforced task status BLOCKED until upstream task reaches COMPLETED.",
                        },
                    ],
                }
            ],
        },

        # =====================================================================
        # SCENARIO 6: SUCCESSFUL COMPLETION (pgvector Semantic RAG Engine)
        # Demonstrates: 100% completion, all milestones COMPLETED, all tasks COMPLETED,
        # past outcome learning memory, closed lifecycle.
        # =====================================================================
        {
            "id": "scenario_6_successful_completion",
            "scenario_name": "Successful Completion",
            "title": "Implement pgvector Semantic RAG Engine with Cross-Encoder Reranking",
            "objective": "Deliver end-to-end vector search retrieval with sub-20ms p95 latency and hybrid keyword reranking.",
            "description": (
                "Completed objective delivering enterprise semantic memory vector store with pgvector, "
                "hybrid lexical/vector reranking, and full test coverage."
            ),
            "priority": "HIGH",
            "status": "COMPLETED",
            "deadline": base_time - timedelta(days=2),
            "success_criteria": [
                "pgvector HNSW index configured with cosine distance metric",
                "Batch embedding pipeline handling 50 chunks concurrently",
                "Retrieval latency benchmarks confirmed < 20ms p95",
            ],
            "constraints": [
                {
                    "type": "latency_sla",
                    "value": "p95 retrieval latency < 20ms",
                    "metadata": {"target_latency_ms": 20},
                }
            ],
            "milestones": [
                {
                    "title": "Schema & Vector Indexing Design",
                    "description": "PostgreSQL schema with 1536-dimensional vector columns and HNSW indexes.",
                    "status": "COMPLETED",
                    "order_index": 1,
                    "deadline": base_time - timedelta(days=14),
                },
                {
                    "title": "Embedding Generation & Semantic Retriever",
                    "description": "Batch embedding generator and hybrid search SQL query builder.",
                    "status": "COMPLETED",
                    "order_index": 2,
                    "deadline": base_time - timedelta(days=7),
                },
                {
                    "title": "Performance Optimization & Benchmarks",
                    "description": "Latency profiling, index warm-up, and automated verification suite.",
                    "status": "COMPLETED",
                    "order_index": 3,
                    "deadline": base_time - timedelta(days=2),
                },
            ],
            "tasks": [
                {
                    "title": "Design pgvector table schema with HNSW index and cosine operator",
                    "description": "Write migration DDL creating memories table with vector(1536) and vector_cosine_ops.",
                    "status": "COMPLETED",
                    "priority": "HIGH",
                    "estimated_minutes": 45,
                    "due_at": base_time - timedelta(days=15),
                    "completed_at": base_time - timedelta(days=15),
                    "milestone_index": 0,
                },
                {
                    "title": "Implement cosine similarity queries and batch embedder service",
                    "description": "Write SQLAlchemy vector query builder and multi-tenant user isolation filters.",
                    "status": "COMPLETED",
                    "priority": "HIGH",
                    "estimated_minutes": 90,
                    "due_at": base_time - timedelta(days=8),
                    "completed_at": base_time - timedelta(days=8),
                    "milestone_index": 1,
                },
                {
                    "title": "Add query caching and latency profiling benchmarks",
                    "description": "Benchmark 100 queries; measure mean latency, standard deviation, and p95 response time.",
                    "status": "COMPLETED",
                    "priority": "MEDIUM",
                    "estimated_minutes": 60,
                    "due_at": base_time - timedelta(days=2),
                    "completed_at": base_time - timedelta(days=2),
                    "milestone_index": 2,
                },
            ],
            "plans": [
                {
                    "version": 1,
                    "status": "ACTIVE",
                    "is_feasible": True,
                    "deadline_risk": 0.0,
                    "risk_level": "LOW",
                    "schedule_utilization": 1.0,
                    "reason": "Plan executed to 100% completion on schedule.",
                    "generated_at": base_time - timedelta(days=16),
                }
            ],
            "memories": [
                {
                    "memory_type": "SEMANTIC",
                    "content": "Semantic pgvector indexing achieved <15ms retrieval latency with hybrid keyword reranking and zero regressions.",
                    "importance_score": 0.95,
                    "confidence": 1.0,
                    "source": "benchmark_suite",
                    "metadata": {"category": "Past outcome", "latency_p95_ms": 14.8, "status": "verified"},
                }
            ],
            "agent_runs": [
                {
                    "trigger": "goal_completion_audit",
                    "summary": "Final verification audit: all milestones and tasks verified complete",
                    "status": "SUCCESS",
                    "duration_ms": 150,
                    "events": [
                        {
                            "event_type": "AGENT_RUN",
                            "status": "SUCCESS",
                            "description": "Initiated goal lifecycle completion review for 'pgvector Semantic RAG Engine'",
                        },
                        {
                            "event_type": "EVALUATION",
                            "status": "SUCCESS",
                            "description": "Verified all 3 phase milestones and all 3 decomposed tasks marked COMPLETED.",
                        },
                        {
                            "event_type": "STATE_UPDATE",
                            "status": "SUCCESS",
                            "description": "Goal status transitioned to COMPLETED. Recorded 'Past outcome' learning memory.",
                        },
                    ],
                }
            ],
        },
    ]
