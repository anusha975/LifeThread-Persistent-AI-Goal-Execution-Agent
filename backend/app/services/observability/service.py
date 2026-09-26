import logging
import math
import threading
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.goal import Goal, GoalStatus
from app.services.agent_trace.models import EventStatus, ExecutionEventType
from app.services.observability.models import (
    AgentObservabilityDashboard,
    AlertSeverity,
    AlertType,
    DiagnosticRunTelemetry,
    GoalProgressMetric,
    LatencyMetric,
    LatencyPercentiles,
    MemoryRetrievalMetric,
    MetricCategory,
    ObservabilityAlert,
    ReplanningMetric,
    TokenUsageMetric,
    ToolMetric,
    ToolObservabilitySummary,
)

logger = logging.getLogger("lifethread.services.observability")


class AgentObservabilityService:
    """Production observability service tracking telemetry, calculating metrics,

    detecting failure patterns, and diagnosing agent runs for operators.
    """

    _lock = threading.RLock()

    # Telemetry storage with rolling bounded deques
    _MAX_RECORDS = 5000
    _latency_records: deque[LatencyMetric] = deque(maxlen=_MAX_RECORDS)
    _tool_records: deque[ToolMetric] = deque(maxlen=_MAX_RECORDS)
    _token_records: deque[TokenUsageMetric] = deque(maxlen=_MAX_RECORDS)
    _memory_records: deque[MemoryRetrievalMetric] = deque(maxlen=_MAX_RECORDS)
    _replan_records: deque[ReplanningMetric] = deque(maxlen=_MAX_RECORDS)
    _goal_records: deque[GoalProgressMetric] = deque(maxlen=_MAX_RECORDS)
    _alerts: list[ObservabilityAlert] = []

    # Failure tracking state machines for alert thresholds
    _consecutive_tool_failures: dict[str, int] = defaultdict(int)
    _goal_replan_timestamps: dict[str, list[datetime]] = defaultdict(list)
    _database_failures_count: int = 0
    _database_failure_events: deque[dict[str, Any]] = deque(maxlen=50)

    # Threshold defaults
    UNUSUALLY_LONG_RUN_THRESHOLD_MS: float = 10000.0  # 10s
    REPEATED_TOOL_FAILURE_THRESHOLD: int = 3
    REPEATED_REPLAN_THRESHOLD: int = 3
    REPEATED_REPLAN_WINDOW_MINUTES: int = 60
    DATABASE_FAILURE_THRESHOLD: int = 2

    # -------------------------------------------------------------------------
    # Latency & Execution Recording
    # -------------------------------------------------------------------------

    @classmethod
    def record_latency(
        cls,
        category: MetricCategory,
        name: str,
        duration_ms: float,
        success: bool = True,
        run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LatencyMetric:
        """Record a general operation latency metric."""
        metric = LatencyMetric(
            category=category,
            name=name,
            duration_ms=max(0.0, float(duration_ms)),
            success=success,
            run_id=run_id,
            metadata=metadata or {},
        )
        with cls._lock:
            cls._latency_records.append(metric)
        return metric

    @classmethod
    def record_agent_run(
        cls,
        run_id: str,
        duration_ms: float,
        status: EventStatus = EventStatus.SUCCESS,
        trigger: str | None = None,
        goal_id: uuid.UUID | None = None,
    ) -> None:
        """Track agent run completion, latency, and evaluate run duration alarms."""
        duration_float = max(0.0, float(duration_ms))
        cls.record_latency(
            category=MetricCategory.AGENT_RUN,
            name=trigger or "agent_run",
            duration_ms=duration_float,
            success=(status == EventStatus.SUCCESS),
            run_id=run_id,
            metadata={"goal_id": str(goal_id) if goal_id else None, "status": status.value},
        )

        # Alert evaluation: Unusually long agent runs
        if duration_float >= cls.UNUSUALLY_LONG_RUN_THRESHOLD_MS:
            cls.raise_alert(
                alert_type=AlertType.UNUSUALLY_LONG_RUN,
                severity=AlertSeverity.WARNING if duration_float < cls.UNUSUALLY_LONG_RUN_THRESHOLD_MS * 2 else AlertSeverity.ERROR,
                title=f"Unusually Long Agent Run Detected: {duration_float:.0f}ms",
                message=(
                    f"Agent run '{run_id}' exceeded latency threshold ({cls.UNUSUALLY_LONG_RUN_THRESHOLD_MS:.0f}ms) "
                    f"with total execution time of {duration_float:.0f}ms."
                ),
                source=f"run:{run_id}",
                details={"run_id": run_id, "duration_ms": duration_float, "threshold_ms": cls.UNUSUALLY_LONG_RUN_THRESHOLD_MS},
            )

    @classmethod
    def record_llm_call(
        cls,
        duration_ms: float,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        model: str | None = None,
        run_id: str | None = None,
        success: bool = True,
    ) -> None:
        """Track foundation model inference latency and token usage."""
        model_name = model or "foundation-model"
        duration_float = max(0.0, float(duration_ms))

        cls.record_latency(
            category=MetricCategory.LLM,
            name=model_name,
            duration_ms=duration_float,
            success=success,
            run_id=run_id,
            metadata={"tokens": prompt_tokens + completion_tokens},
        )

        token_metric = TokenUsageMetric(
            model=model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            run_id=run_id,
        )
        with cls._lock:
            cls._token_records.append(token_metric)

    @classmethod
    def record_mcp_call(
        cls,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
        retry_count: int = 0,
        run_id: str | None = None,
    ) -> None:
        """Track Model Context Protocol (MCP) tool execution latency and outcomes."""
        cls.record_tool_call(
            tool_name=tool_name,
            duration_ms=duration_ms,
            success=success,
            error=error,
            retry_count=retry_count,
            is_mcp=True,
            run_id=run_id,
        )

    @classmethod
    def record_tool_call(
        cls,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
        retry_count: int = 0,
        is_mcp: bool = False,
        run_id: str | None = None,
    ) -> None:
        """Track tool execution latency, retries, failures, and check repeated failure alarms."""
        duration_float = max(0.0, float(duration_ms))
        category = MetricCategory.MCP if is_mcp else MetricCategory.TOOL

        cls.record_latency(
            category=category,
            name=tool_name,
            duration_ms=duration_float,
            success=success,
            run_id=run_id,
            metadata={"is_mcp": is_mcp, "retry_count": retry_count},
        )

        metric = ToolMetric(
            tool_name=tool_name,
            is_mcp=is_mcp,
            duration_ms=duration_float,
            success=success,
            error_type=error.split(":")[0] if error else None,
            error_message=error,
            retry_count=retry_count,
            run_id=run_id,
        )

        with cls._lock:
            cls._tool_records.append(metric)

            # Failure rate & repeated failure alert evaluation
            if success:
                cls._consecutive_tool_failures[tool_name] = 0
            else:
                cls._consecutive_tool_failures[tool_name] += 1
                consecutive = cls._consecutive_tool_failures[tool_name]

                if consecutive >= cls.REPEATED_TOOL_FAILURE_THRESHOLD:
                    cls.raise_alert(
                        alert_type=AlertType.REPEATED_TOOL_FAILURE,
                        severity=AlertSeverity.ERROR if consecutive >= 5 else AlertSeverity.WARNING,
                        title=f"Repeated Tool Failure: {tool_name} ({consecutive} consecutive failures)",
                        message=(
                            f"Tool '{tool_name}' failed {consecutive} consecutive times. "
                            f"Latest error: {error or 'Unknown failure'}"
                        ),
                        source=f"tool:{tool_name}",
                        details={
                            "tool_name": tool_name,
                            "is_mcp": is_mcp,
                            "consecutive_failures": consecutive,
                            "latest_error": error,
                            "run_id": run_id,
                        },
                    )

    @classmethod
    def record_replanning(
        cls,
        goal_id: uuid.UUID | None,
        reason: str,
        previous_version: int = 1,
        new_version: int = 2,
        run_id: str | None = None,
    ) -> None:
        """Track replanning frequency and raise alert if a goal triggers repeated replans."""
        now = datetime.now(UTC)
        metric = ReplanningMetric(
            goal_id=goal_id,
            reason=reason,
            previous_version=previous_version,
            new_version=new_version,
            run_id=run_id,
            timestamp=now,
        )

        with cls._lock:
            cls._replan_records.append(metric)

            if goal_id:
                goal_key = str(goal_id)
                cutoff = now - timedelta(minutes=cls.REPEATED_REPLAN_WINDOW_MINUTES)
                # Keep timestamps within observation window
                valid_stamps = [t for t in cls._goal_replan_timestamps[goal_key] if t >= cutoff]
                valid_stamps.append(now)
                cls._goal_replan_timestamps[goal_key] = valid_stamps

                if len(valid_stamps) >= cls.REPEATED_REPLAN_THRESHOLD:
                    cls.raise_alert(
                        alert_type=AlertType.REPEATED_REPLANNING,
                        severity=AlertSeverity.WARNING,
                        title=f"Repeated Replanning Alert for Goal {goal_key[:8]}",
                        message=(
                            f"Goal {goal_key} replanned {len(valid_stamps)} times in the last "
                            f"{cls.REPEATED_REPLAN_WINDOW_MINUTES} minutes (threshold: {cls.REPEATED_REPLAN_THRESHOLD}). "
                            f"Latest trigger: {reason}."
                        ),
                        source=f"goal:{goal_key}",
                        details={
                            "goal_id": goal_key,
                            "replan_count_in_window": len(valid_stamps),
                            "window_minutes": cls.REPEATED_REPLAN_WINDOW_MINUTES,
                            "latest_reason": reason,
                            "run_id": run_id,
                        },
                    )

    @classmethod
    def record_database_operation(
        cls,
        operation: str,
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Track database query/transaction health and evaluate database failure alarms."""
        duration_float = max(0.0, float(duration_ms))
        cls.record_latency(
            category=MetricCategory.DATABASE,
            name=operation,
            duration_ms=duration_float,
            success=success,
            run_id=run_id,
            metadata={"error": error},
        )

        with cls._lock:
            if not success:
                cls._database_failures_count += 1
                cls._database_failure_events.append({
                    "operation": operation,
                    "error": error,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "run_id": run_id,
                })

                if cls._database_failures_count >= cls.DATABASE_FAILURE_THRESHOLD:
                    cls.raise_alert(
                        alert_type=AlertType.DATABASE_FAILURE,
                        severity=AlertSeverity.CRITICAL,
                        title=f"Database Failure Threshold Exceeded ({cls._database_failures_count} errors)",
                        message=(
                            f"Database encountered {cls._database_failures_count} operational errors. "
                            f"Latest operation '{operation}' failed: {error or 'Unknown error'}"
                        ),
                        source="database",
                        details={
                            "total_failures": cls._database_failures_count,
                            "latest_operation": operation,
                            "latest_error": error,
                            "run_id": run_id,
                        },
                    )
            else:
                # Slowly decay failure count on clean operations
                if cls._database_failures_count > 0:
                    cls._database_failures_count = max(0, cls._database_failures_count - 1)

    @classmethod
    def record_memory_retrieval(
        cls,
        duration_ms: float,
        item_count: int,
        avg_confidence: float = 1.0,
        query: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Track memory and vector context recall performance and relevance."""
        duration_float = max(0.0, float(duration_ms))
        cls.record_latency(
            category=MetricCategory.MEMORY,
            name="memory_retrieval",
            duration_ms=duration_float,
            success=True,
            run_id=run_id,
            metadata={"item_count": item_count, "avg_confidence": avg_confidence},
        )

        metric = MemoryRetrievalMetric(
            query=query,
            duration_ms=duration_float,
            item_count=item_count,
            avg_confidence=avg_confidence,
            run_id=run_id,
        )
        with cls._lock:
            cls._memory_records.append(metric)

    @classmethod
    def record_goal_progress(
        cls,
        goal_id: uuid.UUID,
        goal_title: str,
        progress_percentage: float,
        status: str,
        is_overdue: bool = False,
    ) -> None:
        """Snapshot goal progress telemetry."""
        metric = GoalProgressMetric(
            goal_id=goal_id,
            goal_title=goal_title,
            progress_percentage=progress_percentage,
            status=status,
            is_overdue=is_overdue,
        )
        with cls._lock:
            cls._goal_records.append(metric)

    # -------------------------------------------------------------------------
    # Alert Management
    # -------------------------------------------------------------------------

    @classmethod
    def raise_alert(
        cls,
        alert_type: AlertType,
        severity: AlertSeverity,
        title: str,
        message: str,
        source: str,
        details: dict[str, Any] | None = None,
    ) -> ObservabilityAlert:
        """Create and broadcast an operational alarm."""
        with cls._lock:
            # Deduplicate active identical alerts for the same source within 5 minutes
            cutoff = datetime.now(UTC) - timedelta(minutes=5)
            for existing in cls._alerts:
                if (
                    not existing.resolved
                    and existing.alert_type == alert_type
                    and existing.source == source
                    and existing.created_at >= cutoff
                ):
                    existing.details.update(details or {})
                    existing.title = title
                    existing.message = message
                    return existing

            alert = ObservabilityAlert(
                alert_type=alert_type,
                severity=severity,
                title=title,
                message=message,
                source=source,
                details=details or {},
            )
            cls._alerts.append(alert)
            logger.warning("OBSERVABILITY ALERT [%s/%s] %s: %s", severity.value, alert_type.value, title, message)
            return alert

    @classmethod
    def get_alerts(
        cls,
        resolved: bool | None = None,
        alert_type: AlertType | None = None,
    ) -> list[ObservabilityAlert]:
        """Fetch system observability alerts with optional resolution/type filters."""
        with cls._lock:
            alerts = list(cls._alerts)

        if resolved is not None:
            alerts = [a for a in alerts if a.resolved == resolved]
        if alert_type is not None:
            alerts = [a for a in alerts if a.alert_type == alert_type]

        alerts.sort(key=lambda a: a.created_at, reverse=True)
        return alerts

    @classmethod
    def resolve_alert(cls, alert_id: str) -> bool:
        """Mark an operational alert as resolved."""
        with cls._lock:
            for alert in cls._alerts:
                if alert.id == alert_id:
                    alert.resolved = True
                    alert.resolved_at = datetime.now(UTC)
                    return True
        return False

    # -------------------------------------------------------------------------
    # Calculations & Dashboard Generation
    # -------------------------------------------------------------------------

    @classmethod
    def calculate_percentiles(cls, durations: list[float]) -> LatencyPercentiles:
        """Calculate statistical percentile distribution across latency measurements."""
        if not durations:
            return LatencyPercentiles()

        sorted_d = sorted(durations)
        n = len(sorted_d)

        def _pct(p: float) -> float:
            k = (n - 1) * p
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return float(sorted_d[int(k)])
            d0 = sorted_d[int(f)] * (c - k)
            d1 = sorted_d[int(c)] * (k - f)
            return float(d0 + d1)

        return LatencyPercentiles(
            count=n,
            avg_ms=round(sum(sorted_d) / n, 2),
            p50_ms=round(_pct(0.50), 2),
            p90_ms=round(_pct(0.90), 2),
            p95_ms=round(_pct(0.95), 2),
            p99_ms=round(_pct(0.99), 2),
            min_ms=round(sorted_d[0], 2),
            max_ms=round(sorted_d[-1], 2),
        )

    @classmethod
    async def get_dashboard(cls, db: AsyncSession | None = None) -> AgentObservabilityDashboard:
        """Compile internal observability dashboard aggregating all operational telemetry."""
        with cls._lock:
            latency_list = list(cls._latency_records)
            tool_list = list(cls._tool_records)
            token_list = list(cls._token_records)
            memory_list = list(cls._memory_records)
            replan_list = list(cls._replan_records)
            alerts_list = list(cls._alerts)

        # 1. Latency by Category
        agent_durations = [m.duration_ms for m in latency_list if m.category == MetricCategory.AGENT_RUN]
        llm_durations = [m.duration_ms for m in latency_list if m.category == MetricCategory.LLM]
        mcp_durations = [m.duration_ms for m in latency_list if m.category == MetricCategory.MCP]
        tool_durations = [m.duration_ms for m in latency_list if m.category == MetricCategory.TOOL]
        memory_durations = [m.duration_ms for m in latency_list if m.category == MetricCategory.MEMORY]

        agent_pct = cls.calculate_percentiles(agent_durations)
        llm_pct = cls.calculate_percentiles(llm_durations)
        mcp_pct = cls.calculate_percentiles(mcp_durations)
        tool_pct = cls.calculate_percentiles(tool_durations)
        memory_pct = cls.calculate_percentiles(memory_durations)

        # 2. Tool Metrics & Failure Rates
        tools_map: dict[str, list[ToolMetric]] = defaultdict(list)
        for t in tool_list:
            tools_map[t.tool_name].append(t)

        tool_summaries: list[ToolObservabilitySummary] = []
        total_tool_calls = len(tool_list)
        total_tool_fails = 0
        total_retries = sum(t.retry_count for t in tool_list)

        for name, metrics in tools_map.items():
            calls = len(metrics)
            fails = sum(1 for m in metrics if not m.success)
            total_tool_fails += fails
            is_mcp = any(m.is_mcp for m in metrics)
            avg_dur = sum(m.duration_ms for m in metrics) / calls if calls > 0 else 0.0
            retries = sum(m.retry_count for m in metrics)
            last_err = next((m.error_message for m in reversed(metrics) if m.error_message), None)

            tool_summaries.append(
                ToolObservabilitySummary(
                    tool_name=name,
                    is_mcp=is_mcp,
                    total_calls=calls,
                    success_count=calls - fails,
                    failure_count=fails,
                    failure_rate=round((fails / calls) * 100.0, 2) if calls > 0 else 0.0,
                    avg_duration_ms=round(avg_dur, 2),
                    retry_count=retries,
                    last_error=last_err,
                )
            )

        overall_tool_failure_rate = (
            round((total_tool_fails / total_tool_calls) * 100.0, 2) if total_tool_calls > 0 else 0.0
        )

        # 3. Token Usage
        prompt_tokens = sum(t.prompt_tokens for t in token_list)
        comp_tokens = sum(t.completion_tokens for t in token_list)
        total_tokens = sum(t.total_tokens for t in token_list)
        by_model: dict[str, int] = defaultdict(int)
        for t in token_list:
            by_model[t.model] += t.total_tokens

        token_usage_summary = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": comp_tokens,
            "total_tokens": total_tokens,
            "by_model": dict(by_model),
        }

        # 4. Replanning Metrics
        replan_by_reason: dict[str, int] = defaultdict(int)
        for r in replan_list:
            replan_by_reason[r.reason] += 1

        with cls._lock:
            repeated_replan_goals = [
                g for g, stamps in cls._goal_replan_timestamps.items() if len(stamps) >= cls.REPEATED_REPLAN_THRESHOLD
            ]

        replanning_metrics = {
            "total_count": len(replan_list),
            "by_reason": dict(replan_by_reason),
            "repeated_replan_goals": repeated_replan_goals,
        }

        # 5. Goal Progress Metrics
        goal_summary: dict[str, Any] = {
            "total_goals": 0,
            "avg_progress_pct": 0.0,
            "active_count": 0,
            "overdue_count": 0,
        }
        if db is not None:
            try:
                goals_q = select(Goal)
                goals_res = await db.execute(goals_q)
                goals = list(goals_res.scalars().all())
                now = datetime.now(UTC)
                active = [g for g in goals if g.status == GoalStatus.ACTIVE]
                overdue = [g for g in active if g.deadline and g.deadline < now]
                avg_prog = (sum(g.progress_percentage for g in goals) / len(goals)) if goals else 0.0
                goal_summary = {
                    "total_goals": len(goals),
                    "avg_progress_pct": round(avg_prog, 2),
                    "active_count": len(active),
                    "overdue_count": len(overdue),
                }
            except Exception as e:
                logger.warning("Error fetching goal summary for dashboard: %s", e)

        # 6. Memory Retrieval Summary
        mem_count = len(memory_list)
        mem_avg_lat = (sum(m.duration_ms for m in memory_list) / mem_count) if mem_count > 0 else 0.0
        mem_avg_conf = (sum(m.avg_confidence for m in memory_list) / mem_count) if mem_count > 0 else 1.0
        mem_items = sum(m.item_count for m in memory_list)

        memory_summary = {
            "total_retrievals": mem_count,
            "avg_latency_ms": round(mem_avg_lat, 2),
            "avg_confidence": round(mem_avg_conf, 3),
            "total_items_retrieved": mem_items,
        }

        # 7. Active Alerts & System Health
        active_alerts = [a for a in alerts_list if not a.resolved]
        alert_counts_by_type: dict[str, int] = defaultdict(int)
        has_critical = False
        has_warning = False

        for a in active_alerts:
            alert_counts_by_type[a.alert_type.value] += 1
            if a.severity == AlertSeverity.CRITICAL:
                has_critical = True
            elif a.severity in (AlertSeverity.WARNING, AlertSeverity.ERROR):
                has_warning = True

        system_status = "CRITICAL" if has_critical else ("DEGRADED" if has_warning else "HEALTHY")

        return AgentObservabilityDashboard(
            system_status=system_status,
            agent_latency=agent_pct,
            llm_latency=llm_pct,
            mcp_latency=mcp_pct,
            tool_latency=tool_pct,
            memory_latency=memory_pct,
            tool_metrics=tool_summaries,
            overall_tool_failure_rate=overall_tool_failure_rate,
            total_retries=total_retries,
            token_usage=token_usage_summary,
            replanning_metrics=replanning_metrics,
            goal_progress_summary=goal_summary,
            memory_retrieval_summary=memory_summary,
            active_alerts=active_alerts,
            alert_counts_by_type=dict(alert_counts_by_type),
        )

    # -------------------------------------------------------------------------
    # Acceptance Criteria: Failure Diagnostic from Telemetry
    # -------------------------------------------------------------------------

    @classmethod
    async def diagnose_run(
        cls,
        run_id: str,
        db: AsyncSession | None = None,
    ) -> DiagnosticRunTelemetry:
        """Root cause failure analysis enabling operators to immediately pinpoint

        the reason, stage, and tool responsible for any agent run failure.
        """
        # Look up run from trace service
        run = None
        with cls._lock:
            from app.services.agent_trace.service import AgentTraceService
            run = AgentTraceService._runs.get(run_id)

        if not run:
            return DiagnosticRunTelemetry(
                run_id=run_id,
                status="NOT_FOUND",
                is_failure=True,
                failure_category="UNKNOWN_RUN",
                failure_root_cause=f"Agent run '{run_id}' not found in active telemetry store.",
                operator_recommendations=["Verify run ID or inspect archived telemetry logs."],
            )

        timeline: list[dict[str, Any]] = []
        failing_event: dict[str, Any] | None = None
        failing_stage: str | None = None
        failing_tool: str | None = None
        failure_category = "NONE"
        failure_root_cause = None
        recommendations: list[str] = []

        is_failure = run.status in (EventStatus.FAILED, EventStatus.WARNING)

        for ev in run.events:
            event_dict = {
                "event_type": ev.event_type.value,
                "status": ev.status.value,
                "stage": ev.stage.value if ev.stage else None,
                "short_explanation": ev.short_explanation,
                "tool_name": ev.tool_name,
                "timestamp": ev.timestamp.isoformat(),
            }
            timeline.append(event_dict)

            if ev.status == EventStatus.FAILED and not failing_event:
                failing_event = event_dict
                failing_stage = ev.stage.value if ev.stage else ev.event_type.value
                failing_tool = ev.tool_name

                # Diagnose category and recommendations based on event telemetry
                explanation_lower = ev.short_explanation.lower()
                _metadata_str = str(ev.metadata).lower()

                if "permission" in explanation_lower or "unauthorized" in explanation_lower or "forbidden" in explanation_lower:
                    failure_category = "PERMISSION_DENIED"
                    failure_root_cause = f"Action blocked by permission policy: {ev.short_explanation}"
                    recommendations.extend([
                        "Check user role permissions or grant required action pattern.",
                    ])
                elif "timeout" in explanation_lower or "deadline exceeded" in explanation_lower:
                    failure_category = "TIMEOUT_EXCEEDED"
                    failure_root_cause = f"Execution timed out during stage '{failing_stage}': {ev.short_explanation}"
                    recommendations.extend([
                        "Increase execution timeout or reduce complexity of the requested goal.",
                        "Verify external dependency latency percentiles in the observability dashboard.",
                    ])
                elif "database" in explanation_lower or "db" in explanation_lower or "sqlite" in explanation_lower or "operationalerror" in explanation_lower:
                    failure_category = "DATABASE_ERROR"
                    failure_root_cause = f"Database operation failure during {ev.event_type.value}: {ev.short_explanation}"
                    recommendations.extend([
                        "Check database connection pool and lock contention.",
                        "Inspect recent database schema migrations or connection timeouts.",
                    ])
                elif ev.tool_name or ev.event_type in (ExecutionEventType.TOOL_CALL, ExecutionEventType.TOOL_RESULT):
                    failure_category = "TOOL_EXECUTION_FAILURE"
                    failure_root_cause = f"Tool '{ev.tool_name or 'unknown'}' failed: {ev.short_explanation}"
                    recommendations.extend([
                        f"Verify schema arguments passed to '{ev.tool_name}'.",
                        "Check if the MCP tool provider is healthy and responsive.",
                        "Consider configuring a fallback handler or increasing retry allowance.",
                    ])
                else:
                    failure_category = "APPLICATION_EXCEPTION"
                    failure_root_cause = ev.short_explanation
                    recommendations.append("Inspect application stack trace and orchestrator logs.")

        if not is_failure:
            failure_category = "SUCCESS"
            failure_root_cause = "Agent run completed successfully without errors."
            recommendations.append("No operator action needed.")

        return DiagnosticRunTelemetry(
            run_id=run.id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            status=run.status.value,
            duration_ms=run.duration_ms,
            is_failure=is_failure,
            failure_category=failure_category,
            failure_root_cause=failure_root_cause,
            failing_stage=failing_stage,
            failing_tool=failing_tool,
            error_details=failing_event or {},
            timeline=timeline,
            operator_recommendations=recommendations,
        )

    # -------------------------------------------------------------------------
    # Test Isolation Helper
    # -------------------------------------------------------------------------

    @classmethod
    def reset(cls) -> None:
        """Clear all metrics, counters, and alerts for test isolation."""
        with cls._lock:
            cls._latency_records.clear()
            cls._tool_records.clear()
            cls._token_records.clear()
            cls._memory_records.clear()
            cls._replan_records.clear()
            cls._goal_records.clear()
            cls._alerts.clear()
            cls._consecutive_tool_failures.clear()
            cls._goal_replan_timestamps.clear()
            cls._database_failures_count = 0
            cls._database_failure_events.clear()
