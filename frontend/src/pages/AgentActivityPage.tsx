import React, { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import {
  Activity,
  BrainCircuit,
  Clock,
  Compass,
  Database,
  ExternalLink,
  GitCommit,
  History,
  Layers,
  Play,
  RefreshCw,
  Server,
  ShieldCheck,
  Target,
  Terminal,
  Wrench,
  Workflow,
} from "lucide-react";
import { agentTraceService } from "../services/agentTraceService";
import { EventStatus, ExecutionEventType } from "../types/agentTrace";
import { formatRelativeTime } from "../utils/dashboardMetrics";
import { Button } from "../components/ui/Button";
import { Badge } from "../components/ui/Badge";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";

export const AgentActivityPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialGoalId = searchParams.get("goal_id") || undefined;

  const [selectedGoalId, setSelectedGoalId] = useState<string | undefined>(
    initialGoalId,
  );
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [filterTrigger, setFilterTrigger] = useState<string>("all");

  // 1. Fetch Agent Runs List
  const {
    data: runs = [],
    isLoading: isLoadingRuns,
    isError: isRunsError,
    error: runsError,
    refetch: refetchRuns,
    isFetching: isFetchingRuns,
  } = useQuery({
    queryKey: ["agentRuns", selectedGoalId],
    queryFn: () =>
      agentTraceService.listRuns({ goalId: selectedGoalId, limit: 100 }),
  });

  // Automatically select the first run if none selected
  useEffect(() => {
    if (runs.length > 0 && !selectedRunId) {
      setSelectedRunId(runs[0].id);
    }
  }, [runs, selectedRunId]);

  // 2. Fetch Selected Run Detail & Trace Events
  const {
    data: activeRun,
    isLoading: isLoadingActiveRun,
    isError: isActiveRunError,
    refetch: refetchActiveRun,
  } = useQuery({
    queryKey: ["agentRunDetail", selectedRunId],
    queryFn: () => agentTraceService.getRun(selectedRunId!),
    enabled: Boolean(selectedRunId),
  });

  // Filter runs by trigger
  const filteredRuns = runs.filter((r) => {
    if (filterTrigger === "all") return true;
    return r.trigger === filterTrigger;
  });

  // Distinct triggers for filter pills
  const availableTriggers = Array.from(new Set(runs.map((r) => r.trigger)));

  // Helper mapping event types to distinct icons, labels, and color palettes
  const getEventVisuals = (type: ExecutionEventType) => {
    switch (type) {
      case "AGENT_RUN":
        return {
          label: "Agent Run",
          icon: <Play className="w-4 h-4 text-emerald-400" />,
          containerBg: "bg-emerald-950/20 border-emerald-500/30",
          badgeClass:
            "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
        };
      case "DECISION":
        return {
          label: "Decision",
          icon: <Compass className="w-4 h-4 text-cyan-400" />,
          containerBg: "bg-cyan-950/20 border-cyan-500/30",
          badgeClass: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
        };
      case "TOOL_CALL":
        return {
          label: "Tool Call",
          icon: <Wrench className="w-4 h-4 text-amber-400" />,
          containerBg: "bg-amber-950/20 border-amber-500/30",
          badgeClass: "bg-amber-500/10 text-amber-400 border-amber-500/30",
        };
      case "TOOL_RESULT":
        return {
          label: "Tool Result",
          icon: <Server className="w-4 h-4 text-blue-400" />,
          containerBg: "bg-blue-950/20 border-blue-500/30",
          badgeClass: "bg-blue-500/10 text-blue-400 border-blue-500/30",
        };
      case "EVALUATION":
        return {
          label: "Evaluation",
          icon: <ShieldCheck className="w-4 h-4 text-purple-400" />,
          containerBg: "bg-purple-950/20 border-purple-500/30",
          badgeClass: "bg-purple-500/10 text-purple-400 border-purple-500/30",
        };
      case "STATE_UPDATE":
        return {
          label: "State Update",
          icon: <GitCommit className="w-4 h-4 text-emerald-400" />,
          containerBg: "bg-emerald-950/20 border-emerald-500/30",
          badgeClass:
            "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
        };
      default:
        return {
          label: type,
          icon: <Activity className="w-4 h-4 text-slate-400" />,
          containerBg: "bg-slate-900 border-slate-800",
          badgeClass: "bg-slate-800 text-slate-400 border-slate-700",
        };
    }
  };

  const getStatusBadge = (status: EventStatus) => {
    switch (status) {
      case "SUCCESS":
        return <Badge variant="success">SUCCESS</Badge>;
      case "RUNNING":
        return <Badge variant="active">RUNNING</Badge>;
      case "FAILED":
        return <Badge variant="danger">FAILED</Badge>;
      case "WARNING":
        return <Badge variant="warning">WARNING</Badge>;
      case "SKIPPED":
        return <Badge variant="default">SKIPPED</Badge>;
      default:
        return <Badge variant="default">{status}</Badge>;
    }
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-16">
      {/* ========================================================================= */}
      {/* 1. HEADER & EXECUTIVE 6-PHASE CYCLE BANNER                                */}
      {/* ========================================================================= */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs font-mono uppercase tracking-widest text-emerald-400 font-semibold">
              Execution Observability &amp; Traceability
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight mt-1 flex items-center space-x-2">
            <Workflow className="w-7 h-7 text-emerald-400" />
            <span>Agent Activity Center</span>
          </h1>
          <p className="text-xs sm:text-sm text-slate-400 mt-1 max-w-2xl leading-relaxed">
            Inspect verified autonomous execution traces, tactical decisions,
            tool invocations, and state mutations across all goals.
          </p>
        </div>

        <div className="flex items-center space-x-3 shrink-0">
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              refetchRuns();
              if (selectedRunId) refetchActiveRun();
            }}
            isLoading={isFetchingRuns}
            leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Refresh Traces
          </Button>
        </div>
      </div>

      {/* 6-Phase Autonomous Execution Pipeline Indicator */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 shadow-xl">
        <div className="flex items-center justify-between text-xs font-mono text-slate-400">
          <span className="uppercase tracking-wider font-semibold text-slate-300 flex items-center space-x-2">
            <BrainCircuit className="w-4 h-4 text-emerald-400" />
            <span>Verified 6-Phase Autonomous Trace Cycle</span>
          </span>
          <span className="text-[11px] text-emerald-400 font-semibold bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800/60">
            Safe User-Facing Traces
          </span>
        </div>

        {/* Phase Pipeline Breadcrumbs */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 pt-1">
          {[
            {
              phase: "1. Agent Run",
              desc: "Trigger Initialized",
              icon: <Play className="w-3.5 h-3.5 text-emerald-400" />,
            },
            {
              phase: "2. Decision",
              desc: "Tactical Choice",
              icon: <Compass className="w-3.5 h-3.5 text-cyan-400" />,
            },
            {
              phase: "3. Tool Call",
              desc: "Tool Invoked",
              icon: <Wrench className="w-3.5 h-3.5 text-amber-400" />,
            },
            {
              phase: "4. Tool Result",
              desc: "Verified Output",
              icon: <Server className="w-3.5 h-3.5 text-blue-400" />,
            },
            {
              phase: "5. Evaluation",
              desc: "Constraint Check",
              icon: <ShieldCheck className="w-3.5 h-3.5 text-purple-400" />,
            },
            {
              phase: "6. State Update",
              desc: "DB State Committed",
              icon: <GitCommit className="w-3.5 h-3.5 text-emerald-400" />,
            },
          ].map((item, idx) => (
            <div
              key={idx}
              className="p-2.5 rounded-xl bg-slate-950/80 border border-slate-800 flex flex-col justify-between space-y-1"
            >
              <div className="flex items-center space-x-1.5 text-xs font-semibold text-white">
                {item.icon}
                <span className="truncate">{item.phase}</span>
              </div>
              <div className="text-[10px] font-mono text-slate-400 truncate">
                {item.desc}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Safety & Anti-Hallucination Disclaimer */}
      <div className="p-3.5 rounded-xl bg-slate-950 border border-slate-800/80 flex items-center space-x-3 text-xs text-slate-400">
        <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
        <div>
          <strong className="text-white">Audit &amp; Privacy Shield:</strong>{" "}
          LifeThread displays verified decision explanations, audited tool
          payloads, and real state modifications. Internal model
          chain-of-thought tokens and speculative scratchpads are safely
          redacted.
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 2. MAIN 2-COLUMN SPLIT WORKSPACE: RUNS LIST & EXECUTION TRACE             */}
      {/* ========================================================================= */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* ================= LEFT COLUMN: AGENT RUNS LIST (5 cols) ================= */}
        <div className="lg:col-span-5 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white flex items-center space-x-2">
              <History className="w-4 h-4 text-emerald-400" />
              <span>Execution Runs ({filteredRuns.length})</span>
            </h2>

            {selectedGoalId && (
              <button
                onClick={() => {
                  setSelectedGoalId(undefined);
                  setSearchParams({});
                }}
                className="text-xs text-emerald-400 hover:underline font-mono"
              >
                Clear Goal Filter &times;
              </button>
            )}
          </div>

          {/* Trigger Filter Pills */}
          {availableTriggers.length > 1 && (
            <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 scrollbar-none text-xs">
              <button
                onClick={() => setFilterTrigger("all")}
                className={`px-2.5 py-1 rounded-lg font-medium whitespace-nowrap transition-colors ${
                  filterTrigger === "all"
                    ? "bg-slate-800 text-white"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                All ({runs.length})
              </button>
              {availableTriggers.map((trig) => (
                <button
                  key={trig}
                  onClick={() => setFilterTrigger(trig)}
                  className={`px-2.5 py-1 rounded-lg font-mono text-[11px] whitespace-nowrap transition-colors ${
                    filterTrigger === trig
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                      : "text-slate-400 hover:text-slate-200"
                  }`}
                >
                  {trig}
                </button>
              ))}
            </div>
          )}

          {/* Runs List Items */}
          {isLoadingRuns ? (
            <div className="space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 space-y-2"
                >
                  <div className="flex justify-between">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-4 w-16" />
                  </div>
                  <Skeleton className="h-3 w-full" />
                </div>
              ))}
            </div>
          ) : isRunsError ? (
            <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 text-center space-y-2">
              <p className="text-xs text-rose-300 font-medium">
                {runsError instanceof Error
                  ? runsError.message
                  : "Failed to load agent runs"}
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={() => refetchRuns()}
                leftIcon={<RefreshCw className="w-3 h-3" />}
              >
                Retry
              </Button>
            </div>
          ) : filteredRuns.length === 0 ? (
            <EmptyState
              icon={Workflow}
              title="No Execution Runs Recorded"
              description={
                selectedGoalId
                  ? "No execution runs logged for the selected goal filter."
                  : "When the autonomous agent plans a goal, executes tools, or records learning memories, runs appear here."
              }
              action={
                selectedGoalId
                  ? {
                      label: "Clear Goal Filter",
                      onClick: () => {
                        setSelectedGoalId(undefined);
                        setSearchParams({});
                      },
                    }
                  : undefined
              }
            />
          ) : (
            <div className="space-y-2.5 max-h-[750px] overflow-y-auto pr-1">
              {filteredRuns.map((run) => {
                const isSelected = run.id === selectedRunId;

                return (
                  <div
                    key={run.id}
                    onClick={() => setSelectedRunId(run.id)}
                    className={`p-4 rounded-xl border cursor-pointer transition-all duration-150 space-y-2.5 ${
                      isSelected
                        ? "bg-slate-900 border-emerald-500/50 shadow-lg shadow-emerald-950/30 ring-1 ring-emerald-500/20"
                        : "bg-slate-900/50 border-slate-800 hover:border-slate-700 hover:bg-slate-900/80"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-[11px] font-mono font-semibold uppercase text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800/60">
                        {run.trigger}
                      </span>
                      {getStatusBadge(run.status)}
                    </div>

                    <p className="text-xs text-slate-200 font-medium line-clamp-2 leading-relaxed">
                      {run.summary}
                    </p>

                    {run.goal_title && (
                      <div className="flex items-center space-x-1.5 text-xs text-slate-400">
                        <Target className="w-3.5 h-3.5 text-slate-500" />
                        <span className="truncate">{run.goal_title}</span>
                      </div>
                    )}

                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-500 pt-1 border-t border-slate-800/60">
                      <span>{formatRelativeTime(run.started_at)}</span>
                      <span>
                        {run.duration_ms
                          ? `${run.duration_ms}ms`
                          : "In progress"}{" "}
                        &bull; {run.event_count} events
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* ================= RIGHT COLUMN: EXECUTION TRACE DETAILS (7 cols) ================= */}
        <div className="lg:col-span-7 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-base font-bold text-white flex items-center space-x-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              <span>Execution Trace Pipeline</span>
            </h2>

            {activeRun && (
              <span className="text-xs font-mono text-slate-400">
                Run ID: <code className="text-slate-300">{activeRun.id}</code>
              </span>
            )}
          </div>

          {isLoadingActiveRun ? (
            <div className="space-y-4">
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-44 w-full" />
              <Skeleton className="h-44 w-full" />
            </div>
          ) : isActiveRunError || !activeRun ? (
            <EmptyState
              icon={Workflow}
              title="Select a Run to View Trace"
              description="Click on any agent execution run from the left list to review its complete chronological trace, audited tool payloads, and verified decisions."
            />
          ) : (
            <div className="space-y-6">
              {/* Selected Run Metadata Overview Card */}
              <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-3 shadow-lg">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-800">
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-mono font-bold text-emerald-400 uppercase">
                        {activeRun.trigger}
                      </span>
                      {getStatusBadge(activeRun.status)}
                    </div>
                    <h3 className="text-base font-bold text-white">
                      {activeRun.summary}
                    </h3>
                  </div>

                  <div className="text-right text-xs font-mono text-slate-400 space-y-0.5 shrink-0">
                    <div>
                      Started:{" "}
                      {new Date(activeRun.started_at).toLocaleTimeString()}
                    </div>
                    <div>
                      Duration:{" "}
                      <span className="text-slate-200">
                        {activeRun.duration_ms
                          ? `${activeRun.duration_ms}ms`
                          : "Running"}
                      </span>
                    </div>
                  </div>
                </div>

                {activeRun.goal_id && (
                  <div className="flex items-center justify-between text-xs pt-1">
                    <span className="text-slate-400 flex items-center space-x-1.5">
                      <Target className="w-3.5 h-3.5 text-emerald-400" />
                      <span>
                        Associated Goal:{" "}
                        <strong className="text-slate-200">
                          {activeRun.goal_title || activeRun.goal_id}
                        </strong>
                      </span>
                    </span>
                    <Link
                      to={`/goals/${activeRun.goal_id}`}
                      className="text-emerald-400 hover:text-emerald-300 font-medium inline-flex items-center space-x-1"
                    >
                      <span>Open Workspace</span>
                      <ExternalLink className="w-3 h-3" />
                    </Link>
                  </div>
                )}
              </div>

              {/* Chronological Event Pipeline Stack */}
              <div className="space-y-4">
                <h4 className="text-xs uppercase font-mono tracking-wider text-slate-400 flex items-center justify-between">
                  <span>
                    Chronological Trace Progression ({activeRun.events.length}{" "}
                    Steps)
                  </span>
                  <span className="text-[11px] text-slate-500 font-mono">
                    Agent Run &rarr; Decision &rarr; Tool Call &rarr; Result
                    &rarr; Evaluation &rarr; State Update
                  </span>
                </h4>

                <div className="relative pl-6 space-y-5 before:absolute before:left-2.5 before:top-3 before:bottom-3 before:w-0.5 before:bg-slate-800">
                  {activeRun.events.map((event, idx) => {
                    const visuals = getEventVisuals(event.event_type);

                    return (
                      <div key={event.id || idx} className="relative group">
                        {/* Pipeline Node Marker */}
                        <div className="absolute -left-6 mt-1 w-5 h-5 rounded-full bg-slate-950 border-2 border-slate-700 flex items-center justify-center text-[10px] font-mono text-slate-400 group-hover:border-emerald-400 transition-colors">
                          {idx + 1}
                        </div>

                        {/* Event Card */}
                        <div
                          className={`p-4 rounded-xl border ${visuals.containerBg} space-y-2.5 shadow-md hover:border-slate-600 transition-colors`}
                        >
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex items-center space-x-2">
                              <span
                                className={`inline-flex items-center space-x-1.5 px-2 py-0.5 rounded text-xs font-mono font-semibold border ${visuals.badgeClass}`}
                              >
                                {visuals.icon}
                                <span>{visuals.label}</span>
                              </span>
                              {getStatusBadge(event.status)}
                            </div>

                            <div className="text-[11px] font-mono text-slate-400 flex items-center space-x-1.5">
                              <Clock className="w-3 h-3 text-slate-500" />
                              <span>
                                {new Date(event.timestamp).toLocaleTimeString(
                                  undefined,
                                  {
                                    hour: "2-digit",
                                    minute: "2-digit",
                                    second: "2-digit",
                                  },
                                )}
                              </span>
                              <span className="text-slate-600">&bull;</span>
                              <span>{formatRelativeTime(event.timestamp)}</span>
                            </div>
                          </div>

                          {/* Safe User-Facing Explanation */}
                          <p className="text-xs sm:text-sm text-slate-100 font-medium leading-relaxed">
                            {event.short_explanation}
                          </p>

                          {/* Tool Invocations and Parameters if TOOL_CALL */}
                          {event.tool_name && (
                            <div className="p-3 rounded-lg bg-slate-950/80 border border-slate-800/80 space-y-1.5 font-mono text-xs">
                              <div className="flex items-center space-x-2 text-slate-400">
                                <Terminal className="w-3.5 h-3.5 text-amber-400" />
                                <span>Invoked Tool:</span>
                                <code className="text-amber-300 font-semibold">
                                  {event.tool_name}
                                </code>
                              </div>
                              {event.tool_parameters &&
                                Object.keys(event.tool_parameters).length >
                                  0 && (
                                  <div className="text-[11px] text-slate-400 pt-1">
                                    <span className="text-slate-500">
                                      Parameters:{" "}
                                    </span>
                                    <code>
                                      {JSON.stringify(event.tool_parameters)}
                                    </code>
                                  </div>
                                )}
                            </div>
                          )}

                          {/* Tool Results if TOOL_RESULT */}
                          {event.tool_result &&
                            Object.keys(event.tool_result).length > 0 && (
                              <div className="p-3 rounded-lg bg-slate-950/80 border border-slate-800/80 space-y-1 font-mono text-xs">
                                <div className="text-slate-400 flex items-center space-x-2">
                                  <Server className="w-3.5 h-3.5 text-blue-400" />
                                  <span>Tool Execution Payload:</span>
                                </div>
                                <code className="text-[11px] text-blue-300 block overflow-x-auto">
                                  {JSON.stringify(event.tool_result)}
                                </code>
                              </div>
                            )}

                          {/* State Changes if STATE_UPDATE */}
                          {event.state_changes &&
                            Object.keys(event.state_changes).length > 0 && (
                              <div className="p-3 rounded-lg bg-slate-950/80 border border-slate-800/80 space-y-1 font-mono text-xs">
                                <div className="text-slate-400 flex items-center space-x-2">
                                  <Database className="w-3.5 h-3.5 text-emerald-400" />
                                  <span>Committed Mutations:</span>
                                </div>
                                <code className="text-[11px] text-emerald-300 block overflow-x-auto">
                                  {JSON.stringify(event.state_changes)}
                                </code>
                              </div>
                            )}

                          {/* Associated Goal / Task tags */}
                          {(event.goal_title || event.task_title) && (
                            <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-slate-400 font-mono">
                              {event.goal_title && (
                                <span className="flex items-center space-x-1">
                                  <Target className="w-3 h-3 text-slate-500" />
                                  <span>Goal: {event.goal_title}</span>
                                </span>
                              )}
                              {event.task_title && (
                                <span className="flex items-center space-x-1">
                                  <Layers className="w-3 h-3 text-slate-500" />
                                  <span>Task: {event.task_title}</span>
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
