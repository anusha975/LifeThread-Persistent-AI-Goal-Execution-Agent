import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  GitBranch,
  History,
  MinusCircle,
  PlusCircle,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
  Sliders,
  Sparkles,
  Workflow,
} from "lucide-react";
import { goalService } from "../../services/goalService";
import { GoalPriority } from "../../types/goal";
import { ReplanningDiffResponse } from "../../types/replanning";
import { formatRelativeTime } from "../../utils/dashboardMetrics";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";
import { Card, CardContent } from "../ui/Card";
import { Modal } from "../ui/Modal";
import { Skeleton } from "../ui/Skeleton";
import { Alert } from "../ui/Alert";

interface ReplanningDiffViewerProps {
  goalId: string;
  goalTitle?: string;
  onNavigateToTask?: (taskId: string) => void;
}

export const ReplanningDiffViewer: React.FC<ReplanningDiffViewerProps> = ({
  goalId,
  goalTitle,
  onNavigateToTask,
}) => {
  const queryClient = useQueryClient();

  // Version selection for arbitrary comparison
  const [selectedVersionA, setSelectedVersionA] = useState<number | undefined>(
    undefined,
  );
  const [selectedVersionB, setSelectedVersionB] = useState<number | undefined>(
    undefined,
  );

  // Active change filter tab
  const [activeChangesTab, setActiveChangesTab] = useState<
    "all" | "added" | "removed" | "rescheduled" | "priorities"
  >("all");

  // Trigger Replan modal state
  const [isSimulateModalOpen, setIsSimulateModalOpen] = useState(false);
  const [simReason, setSimReason] = useState("DEADLINE_CHANGED");
  const [simDescription, setSimDescription] = useState(
    "Deadline brought forward by 48 hours due to stakeholder request",
  );
  const [simDailyHours, setSimDailyHours] = useState(4.0);
  const [simulateError, setSimulateError] = useState<string | null>(null);

  // 1. Fetch Plan Versions List (for version dropdowns)
  const { data: plansData } = useQuery({
    queryKey: ["goalPlans", goalId],
    queryFn: () => goalService.getPlans(goalId),
    enabled: Boolean(goalId),
  });

  // 2. Fetch Replanning Diff from real backend endpoint
  const {
    data: diffData,
    isLoading: isLoadingDiff,
    isError: isDiffError,
    refetch: refetchDiff,
    isFetching: isFetchingDiff,
  } = useQuery<ReplanningDiffResponse>({
    queryKey: [
      "goalReplanningDiff",
      goalId,
      selectedVersionA,
      selectedVersionB,
    ],
    queryFn: () =>
      goalService.getReplanningDiff(goalId, selectedVersionA, selectedVersionB),
    enabled: Boolean(goalId),
  });

  // Mutation to trigger real replanning event
  const triggerReplanMutation = useMutation({
    mutationFn: (payload: {
      reason: string;
      description: string;
      details?: Record<string, unknown>;
    }) => goalService.triggerReplan(goalId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["goalReplanningDiff", goalId],
      });
      queryClient.invalidateQueries({ queryKey: ["goalPlans", goalId] });
      queryClient.invalidateQueries({ queryKey: ["goalActivePlan", goalId] });
      queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
      setIsSimulateModalOpen(false);
      setSimulateError(null);
    },
    onError: (err: any) => {
      setSimulateError(err?.message || "Failed to trigger replanning");
    },
  });

  const handleSimulateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!simDescription.trim()) {
      setSimulateError("Description is required");
      return;
    }
    triggerReplanMutation.mutate({
      reason: simReason,
      description: simDescription.trim(),
      details: {
        daily_available_hours: simDailyHours,
        triggered_at: new Date().toISOString(),
      },
    });
  };

  const planVersions = plansData?.items || [];
  const changes = diffData?.changes;
  const prevPlan = diffData?.previous_plan;
  const newPlan = diffData?.new_plan;
  const priorityChanges =
    diffData?.priority_changes || changes?.priority_changes || [];

  const addedCount = changes?.tasks_added?.length || 0;
  const removedCount = changes?.tasks_removed?.length || 0;
  const rescheduledCount = changes?.tasks_rescheduled?.length || 0;
  const priorityCount = priorityChanges.length;
  const totalChangesCount =
    addedCount + removedCount + rescheduledCount + priorityCount;

  const getPriorityBadgeClass = (prio: GoalPriority | string) => {
    const p = String(prio).toLowerCase();
    switch (p) {
      case "critical":
        return "bg-rose-500/20 text-rose-300 border-rose-500/40";
      case "high":
        return "bg-orange-500/20 text-orange-300 border-orange-500/40";
      case "medium":
        return "bg-blue-500/20 text-blue-300 border-blue-500/40";
      default:
        return "bg-slate-700 text-slate-300 border-slate-600";
    }
  };

  const formatScheduleWindow = (
    startStr?: string | null,
    endStr?: string | null,
  ) => {
    if (!startStr || !endStr) return "Unscheduled";
    const s = new Date(startStr);
    const e = new Date(endStr);
    return `${s.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${s.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })} - ${e.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${e.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}`;
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-16">
      {/* ========================================================================= */}
      {/* 1. TOP CONTROL BAR & VERSION SELECTOR                                     */}
      {/* ========================================================================= */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-slate-800">
        <div className="space-y-1">
          <div className="flex items-center space-x-2">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs font-mono uppercase tracking-widest text-emerald-400 font-semibold">
              Autonomous Replanning Engine
            </span>
            {isFetchingDiff && (
              <span className="text-[11px] text-slate-500 font-mono flex items-center space-x-1">
                <RefreshCw className="w-3 h-3 animate-spin" />
                <span>Comparing...</span>
              </span>
            )}
          </div>
          <h2 className="text-xl sm:text-2xl font-extrabold text-white tracking-tight flex items-center space-x-2">
            <span>Replanning Visualization &amp; Plan Diff</span>
          </h2>
          <p className="text-xs text-slate-400">
            {goalTitle && (
              <span className="text-slate-300 font-semibold mr-1.5">
                Goal: {goalTitle} &bull;
              </span>
            )}
            Real-time visual comparison of schedule adaptations across
            constraint shifts, failures, and deadline updates.
          </p>
        </div>

        {/* Action Controls & Compare Selectors */}
        <div className="flex items-center space-x-3 shrink-0">
          {planVersions.length >= 2 && (
            <div className="flex items-center space-x-2 text-xs font-mono bg-slate-900/90 border border-slate-800 rounded-lg px-2.5 py-1.5">
              <span className="text-slate-400">Compare:</span>
              <select
                value={selectedVersionA ?? (prevPlan?.version || 1)}
                onChange={(e) => setSelectedVersionA(Number(e.target.value))}
                className="bg-slate-950 border border-slate-800 rounded px-1.5 py-0.5 text-slate-200 text-xs focus:outline-none focus:border-emerald-500"
              >
                {planVersions.map((p) => (
                  <option key={`a-${p.id}`} value={p.version}>
                    v{p.version}
                  </option>
                ))}
              </select>
              <ArrowRight className="w-3 h-3 text-slate-500" />
              <select
                value={
                  selectedVersionB ??
                  (newPlan?.version ||
                    planVersions[planVersions.length - 1]?.version)
                }
                onChange={(e) => setSelectedVersionB(Number(e.target.value))}
                className="bg-slate-950 border border-slate-800 rounded px-1.5 py-0.5 text-slate-200 text-xs focus:outline-none focus:border-emerald-500"
              >
                {planVersions.map((p) => (
                  <option key={`b-${p.id}`} value={p.version}>
                    v{p.version} {p.status === "ACTIVE" ? "(Active)" : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            onClick={() => refetchDiff()}
            className="p-2 rounded-lg bg-slate-800/60 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700/60 transition-colors"
            title="Refresh diff"
            aria-label="Refresh diff"
          >
            <RefreshCw
              className={`w-4 h-4 ${isFetchingDiff ? "animate-spin" : ""}`}
            />
          </button>

          <Button
            onClick={() => {
              setSimulateError(null);
              setIsSimulateModalOpen(true);
            }}
            variant="outline"
            size="sm"
            leftIcon={<RotateCcw className="w-3.5 h-3.5 text-emerald-400" />}
          >
            Trigger Replan
          </Button>
        </div>
      </div>

      {isLoadingDiff ? (
        <div className="space-y-6">
          <Skeleton className="h-28 w-full" />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Skeleton className="h-44 w-full" />
            <Skeleton className="h-44 w-full" />
          </div>
          <Skeleton className="h-64 w-full" />
        </div>
      ) : isDiffError ? (
        <Alert variant="error">
          Failed to retrieve replanning diff from backend. Please verify backend
          service availability.
        </Alert>
      ) : !diffData || !diffData.plan_changed ? (
        <Card className="text-center py-16 border-dashed border-slate-800">
          <CardContent className="space-y-4">
            <div className="w-12 h-12 rounded-full bg-slate-800/80 flex items-center justify-center mx-auto text-slate-400">
              <CheckCircle2 className="w-6 h-6 text-emerald-400" />
            </div>
            <div className="space-y-1">
              <h3 className="text-base font-semibold text-white">
                Baseline Plan v1 Active
              </h3>
              <p className="text-xs text-slate-400 max-w-md mx-auto">
                No replanning events have modified the baseline execution
                schedule yet. When a task slips, deadline shifts, or available
                hours change, LifeThread will automatically generate an
                explainable Plan Diff.
              </p>
            </div>
            <Button
              onClick={() => setIsSimulateModalOpen(true)}
              size="sm"
              leftIcon={<RotateCcw className="w-3.5 h-3.5" />}
            >
              Simulate Constraint Shift
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-6">
          {/* ========================================================================= */}
          {/* 2. THE CORE EXPERIENCE BANNER: "PLAN CHANGED"                             */}
          {/* ========================================================================= */}
          <section
            aria-label="Plan Changed Banner"
            className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-emerald-950/70 via-slate-900/90 to-slate-950 border border-emerald-500/40 p-6 sm:p-7 shadow-2xl space-y-4 ring-1 ring-emerald-500/20"
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center space-x-3">
                <span className="flex h-3 w-3 relative">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500" />
                </span>
                <span className="text-xl sm:text-2xl font-black tracking-tight text-white uppercase font-mono">
                  {diffData.status_label || "PLAN CHANGED"}
                </span>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  Plan v{prevPlan?.version || 1} &rarr; Plan v
                  {newPlan?.version || 2}
                </span>
              </div>

              <div className="flex items-center space-x-2">
                <Badge variant={newPlan?.is_feasible ? "success" : "danger"}>
                  {newPlan?.is_feasible
                    ? "FEASIBLE CANDIDATE"
                    : "INFEASIBLE ALERT"}
                </Badge>
                {diffData.committed_at && (
                  <span className="text-[11px] font-mono text-slate-400">
                    Committed {formatRelativeTime(diffData.committed_at)}
                  </span>
                )}
              </div>
            </div>

            {/* Reason Block */}
            <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800/80 space-y-1">
              <div className="text-[11px] font-mono uppercase tracking-wider text-slate-400 font-semibold flex items-center space-x-1.5">
                <Workflow className="w-3.5 h-3.5 text-emerald-400" />
                <span>Trigger Reason:</span>
                <span className="px-2 py-0.2 rounded bg-slate-800 text-emerald-300 font-mono text-xs">
                  {diffData.reason}
                </span>
              </div>
              <p className="text-sm text-slate-200 font-medium pt-0.5">
                {diffData.why_explanation}
              </p>
            </div>
          </section>

          {/* ========================================================================= */}
          {/* 3. "WHY?" EXPLANATION SECTION                                             */}
          {/* ========================================================================= */}
          <section
            aria-label="Why Explanation Section"
            className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-4 shadow-lg"
          >
            <div className="flex items-center justify-between pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center space-x-2">
                <Sparkles className="w-4 h-4 text-emerald-400" />
                <span>WHY DID THE PLAN CHANGE?</span>
              </h3>
              <div className="text-[11px] font-mono text-slate-500 flex items-center space-x-1">
                <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
                <span>
                  Safe User-Facing Explanation &bull; Private CoT Omitted
                </span>
              </div>
            </div>

            <div className="space-y-3">
              <p className="text-sm font-medium text-slate-200 leading-relaxed bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                {diffData.why_explanation}
              </p>

              {/* Feasibility Rationale */}
              {diffData.why_feasible && (
                <div className="p-4 rounded-xl bg-emerald-950/10 border border-emerald-800/40 text-xs space-y-1">
                  <div className="font-mono text-emerald-400 font-semibold uppercase tracking-wider flex items-center space-x-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    <span>Operational Feasibility Proof</span>
                  </div>
                  <p className="text-slate-300 leading-relaxed">
                    {diffData.why_feasible}
                  </p>
                </div>
              )}
            </div>
          </section>

          {/* ========================================================================= */}
          {/* 4. REAL DATA SIDE-BY-SIDE COMPARISON: PREVIOUS PLAN vs NEW PLAN           */}
          {/* ========================================================================= */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
            {/* Previous Plan Card */}
            <div className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5 space-y-4 shadow-md">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <div className="flex items-center space-x-2">
                  <History className="w-4 h-4 text-slate-400" />
                  <span className="text-sm font-bold text-slate-300">
                    Previous Plan (v{prevPlan?.version || 1})
                  </span>
                </div>
                <Badge variant="default">
                  {prevPlan?.status || "SUPERSEDED"}
                </Badge>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Tasks Count
                  </span>
                  <div className="text-lg font-bold font-mono text-slate-200">
                    {prevPlan?.task_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Workload Duration
                  </span>
                  <div className="text-lg font-bold font-mono text-slate-200">
                    {prevPlan?.total_duration_minutes ?? 0}m
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Scheduled Finish
                  </span>
                  <div className="font-mono text-slate-200 truncate">
                    {prevPlan?.scheduled_end
                      ? new Date(prevPlan.scheduled_end).toLocaleDateString(
                          undefined,
                          {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          },
                        )
                      : "N/A"}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Risk Level
                  </span>
                  <div>
                    <span
                      className={`text-xs font-mono font-bold uppercase px-2 py-0.5 rounded ${
                        prevPlan?.risk_level === "CRITICAL" ||
                        prevPlan?.risk_level === "HIGH"
                          ? "bg-rose-500/20 text-rose-300"
                          : "bg-emerald-500/20 text-emerald-300"
                      }`}
                    >
                      {prevPlan?.risk_level || "LOW"}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* New Plan Card */}
            <div className="rounded-2xl border border-emerald-500/40 bg-slate-900/80 p-5 space-y-4 shadow-xl ring-1 ring-emerald-500/20">
              <div className="flex items-center justify-between pb-3 border-b border-slate-800">
                <div className="flex items-center space-x-2">
                  <Sparkles className="w-4 h-4 text-emerald-400" />
                  <span className="text-sm font-bold text-white">
                    New Plan (v{newPlan?.version || 2})
                  </span>
                </div>
                <Badge variant={newPlan?.is_feasible ? "success" : "danger"}>
                  {newPlan?.is_feasible ? "FEASIBLE" : "INFEASIBLE"}
                </Badge>
              </div>

              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="p-3 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Tasks Count
                  </span>
                  <div className="text-lg font-bold font-mono text-emerald-400">
                    {newPlan?.task_count ?? 0}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Workload Duration
                  </span>
                  <div className="text-lg font-bold font-mono text-emerald-400">
                    {newPlan?.total_duration_minutes ?? 0}m
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Scheduled Finish
                  </span>
                  <div className="font-mono text-emerald-300 font-medium truncate">
                    {newPlan?.scheduled_end
                      ? new Date(newPlan.scheduled_end).toLocaleDateString(
                          undefined,
                          {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          },
                        )
                      : "N/A"}
                  </div>
                </div>

                <div className="p-3 rounded-xl bg-slate-950/80 border border-slate-800 space-y-1">
                  <span className="text-slate-500 font-mono text-[11px]">
                    Risk Level
                  </span>
                  <div>
                    <span
                      className={`text-xs font-mono font-bold uppercase px-2 py-0.5 rounded ${
                        newPlan?.risk_level === "CRITICAL" ||
                        newPlan?.risk_level === "HIGH"
                          ? "bg-rose-500/20 text-rose-300"
                          : "bg-emerald-500/20 text-emerald-300"
                      }`}
                    >
                      {newPlan?.risk_level || "LOW"}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* ========================================================================= */}
          {/* 5. CHANGES BREAKDOWN TABS & DETAILED LIST (The 4 Change Categories)        */}
          {/* ========================================================================= */}
          <section
            aria-label="Structural Changes Breakdown"
            className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 space-y-6 shadow-lg"
          >
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
              <div>
                <h3 className="text-base font-bold text-white flex items-center space-x-2">
                  <GitBranch className="w-4 h-4 text-emerald-400" />
                  <span>Structural Plan Changes ({totalChangesCount})</span>
                </h3>
                <p className="text-xs text-slate-400">
                  Granular task modifications made to satisfy revised scheduling
                  constraints
                </p>
              </div>

              {/* Sub-filter tabs */}
              <div className="flex items-center space-x-1.5 overflow-x-auto">
                <button
                  onClick={() => setActiveChangesTab("all")}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors border ${
                    activeChangesTab === "all"
                      ? "bg-slate-800 text-white border-slate-700"
                      : "bg-slate-950/60 text-slate-400 border-slate-800 hover:text-slate-200"
                  }`}
                >
                  All ({totalChangesCount})
                </button>
                <button
                  onClick={() => setActiveChangesTab("added")}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors border ${
                    activeChangesTab === "added"
                      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                      : "bg-slate-950/60 text-slate-400 border-slate-800 hover:text-slate-200"
                  }`}
                >
                  Added (+{addedCount})
                </button>
                <button
                  onClick={() => setActiveChangesTab("removed")}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors border ${
                    activeChangesTab === "removed"
                      ? "bg-rose-500/20 text-rose-300 border-rose-500/40"
                      : "bg-slate-950/60 text-slate-400 border-slate-800 hover:text-slate-200"
                  }`}
                >
                  Removed (-{removedCount})
                </button>
                <button
                  onClick={() => setActiveChangesTab("rescheduled")}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors border ${
                    activeChangesTab === "rescheduled"
                      ? "bg-sky-500/20 text-sky-300 border-sky-500/40"
                      : "bg-slate-950/60 text-slate-400 border-slate-800 hover:text-slate-200"
                  }`}
                >
                  Rescheduled (&Delta;{rescheduledCount})
                </button>
                <button
                  onClick={() => setActiveChangesTab("priorities")}
                  className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors border ${
                    activeChangesTab === "priorities"
                      ? "bg-purple-500/20 text-purple-300 border-purple-500/40"
                      : "bg-slate-950/60 text-slate-400 border-slate-800 hover:text-slate-200"
                  }`}
                >
                  Priorities ({priorityCount})
                </button>
              </div>
            </div>

            {/* List of Changes */}
            <div className="space-y-3">
              {/* 1. Added Tasks */}
              {(activeChangesTab === "all" || activeChangesTab === "added") &&
                changes?.tasks_added?.map((task, i) => (
                  <div
                    key={`add-${task.task_id || i}`}
                    className="p-4 rounded-xl border border-emerald-500/30 bg-emerald-950/10 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center space-x-2">
                        <PlusCircle className="w-4 h-4 text-emerald-400 shrink-0" />
                        <span className="text-sm font-semibold text-emerald-200">
                          {task.title}
                        </span>
                        <span
                          className={`text-[10px] font-mono uppercase px-2 py-0.2 rounded border ${getPriorityBadgeClass(
                            task.priority,
                          )}`}
                        >
                          {task.priority}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 font-mono pl-6">
                        Added window:{" "}
                        {formatScheduleWindow(
                          task.scheduled_start,
                          task.scheduled_end,
                        )}
                      </div>
                    </div>

                    <div className="flex items-center space-x-2 self-start sm:self-center">
                      <span className="text-xs font-mono font-bold text-emerald-400">
                        +ADDED
                      </span>
                      {onNavigateToTask && task.task_id && (
                        <button
                          type="button"
                          onClick={() => onNavigateToTask(task.task_id)}
                          className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                          title="View task in workspace"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}

              {/* 2. Removed Tasks */}
              {(activeChangesTab === "all" || activeChangesTab === "removed") &&
                changes?.tasks_removed?.map((task, i) => (
                  <div
                    key={`rem-${task.task_id || i}`}
                    className="p-4 rounded-xl border border-rose-500/30 bg-rose-950/10 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                  >
                    <div className="flex items-center space-x-2">
                      <MinusCircle className="w-4 h-4 text-rose-400 shrink-0" />
                      <span className="text-sm font-semibold text-rose-200 line-through">
                        {task.title}
                      </span>
                    </div>

                    <span className="text-xs font-mono font-bold text-rose-400 self-start sm:self-center">
                      -REMOVED
                    </span>
                  </div>
                ))}

              {/* 3. Rescheduled Tasks */}
              {(activeChangesTab === "all" ||
                activeChangesTab === "rescheduled") &&
                changes?.tasks_rescheduled?.map((item) => (
                  <div
                    key={`resched-${item.task_id}`}
                    className="p-4 rounded-xl border border-sky-500/30 bg-sky-950/10 space-y-2.5"
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                      <div className="flex items-center space-x-2">
                        <Clock className="w-4 h-4 text-sky-400 shrink-0" />
                        <span className="text-sm font-semibold text-sky-200">
                          {item.title}
                        </span>
                        <span
                          className={`text-[10px] font-mono uppercase px-2 py-0.2 rounded border ${getPriorityBadgeClass(
                            item.priority,
                          )}`}
                        >
                          {item.priority}
                        </span>
                      </div>

                      <div className="flex items-center space-x-2">
                        <span
                          className={`text-xs font-mono font-bold px-2 py-0.5 rounded ${
                            item.shift_hours > 0
                              ? "bg-amber-500/20 text-amber-300"
                              : "bg-emerald-500/20 text-emerald-300"
                          }`}
                        >
                          {item.shift_hours > 0
                            ? `+${item.shift_hours}h DELAYED`
                            : `${item.shift_hours}h MOVED UP`}
                        </span>
                        {onNavigateToTask && item.task_id && (
                          <button
                            type="button"
                            onClick={() => onNavigateToTask(item.task_id)}
                            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                            title="View task in workspace"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Timeline Comparison */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs font-mono pl-6">
                      <div className="text-slate-400 line-through">
                        Previous:{" "}
                        {formatScheduleWindow(item.old_start, item.old_end)}
                      </div>
                      <div className="text-sky-300 font-medium">
                        Revised:{" "}
                        {formatScheduleWindow(item.new_start, item.new_end)}
                      </div>
                    </div>

                    {item.rationale && (
                      <div className="text-xs text-slate-400 italic pl-6">
                        Rationale: {item.rationale}
                      </div>
                    )}
                  </div>
                ))}

              {/* 4. Changed Priorities */}
              {(activeChangesTab === "all" ||
                activeChangesTab === "priorities") &&
                priorityChanges.map((p) => (
                  <div
                    key={`prio-${p.task_id}`}
                    className="p-4 rounded-xl border border-purple-500/30 bg-purple-950/10 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center space-x-2">
                        <Sliders className="w-4 h-4 text-purple-400 shrink-0" />
                        <span className="text-sm font-semibold text-purple-200">
                          {p.title}
                        </span>
                      </div>
                      <div className="text-xs text-slate-400 pl-6">
                        {p.rationale}
                      </div>
                    </div>

                    <div className="flex items-center space-x-2 self-start sm:self-center font-mono text-xs">
                      <span
                        className={`px-2 py-0.5 rounded border ${getPriorityBadgeClass(p.old_priority)}`}
                      >
                        {p.old_priority}
                      </span>
                      <ArrowRight className="w-3.5 h-3.5 text-purple-400" />
                      <span
                        className={`px-2 py-0.5 rounded border ${getPriorityBadgeClass(p.new_priority)} font-bold`}
                      >
                        {p.new_priority}
                      </span>
                      {onNavigateToTask && p.task_id && (
                        <button
                          type="button"
                          onClick={() => onNavigateToTask(p.task_id)}
                          className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                          title="View task in workspace"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </button>
                      )}
                    </div>
                  </div>
                ))}

              {totalChangesCount === 0 && (
                <div className="text-center py-8 text-xs text-slate-400">
                  No structural task changes detected between selected plan
                  versions.
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 6. MODAL: SIMULATE / TRIGGER REPLAN                                       */}
      {/* ========================================================================= */}
      {isSimulateModalOpen && (
        <Modal
          isOpen={isSimulateModalOpen}
          onClose={() => setIsSimulateModalOpen(false)}
          title="Trigger Autonomous Replanning Event"
        >
          <form onSubmit={handleSimulateSubmit} className="space-y-4">
            <p className="text-xs text-slate-400">
              Submit a real execution or constraint shift. The Autonomous
              Replanning Engine will recalculate the critical path, check
              feasibility, commit the new plan version, and compute the
              explainable Plan Diff.
            </p>

            {simulateError && <Alert variant="error">{simulateError}</Alert>}

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">
                Trigger Reason
              </label>
              <select
                value={simReason}
                onChange={(e) => setSimReason(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700/80 rounded-lg p-2.5 text-xs text-slate-200 focus:outline-none focus:border-emerald-500 font-mono"
              >
                <option value="DEADLINE_CHANGED">DEADLINE_CHANGED</option>
                <option value="AVAILABLE_TIME_CHANGED">
                  AVAILABLE_TIME_CHANGED
                </option>
                <option value="TASK_FAILED">TASK_FAILED</option>
                <option value="TASK_BLOCKED">TASK_BLOCKED</option>
                <option value="PRIORITY_CHANGED">PRIORITY_CHANGED</option>
                <option value="NEW_REQUIREMENT">NEW_REQUIREMENT</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">
                Description of Real-World Event
              </label>
              <textarea
                value={simDescription}
                onChange={(e) => setSimDescription(e.target.value)}
                rows={3}
                className="w-full bg-slate-900 border border-slate-700/80 rounded-lg p-3 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500"
                placeholder="Explain the constraint shift..."
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">
                Adjust Daily Capacity ({simDailyHours} hours/day)
              </label>
              <input
                type="range"
                min="1.0"
                max="12.0"
                step="0.5"
                value={simDailyHours}
                onChange={(e) => setSimDailyHours(parseFloat(e.target.value))}
                className="w-full accent-emerald-500 cursor-pointer"
              />
            </div>

            <div className="pt-3 border-t border-slate-800 flex items-center justify-end space-x-2">
              <Button
                type="button"
                onClick={() => setIsSimulateModalOpen(false)}
                variant="outline"
                size="sm"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={triggerReplanMutation.isPending}
                size="sm"
              >
                {triggerReplanMutation.isPending
                  ? "Replanning..."
                  : "Execute Replan"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
};
