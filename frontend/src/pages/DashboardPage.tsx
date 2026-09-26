import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Calendar,
  CheckCircle2,
  Clock,
  ExternalLink,
  Flame,
  Pause,
  Play,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Target,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { goalService } from '../services/goalService';
import { activityService } from '../services/activityService';
import { Goal, GoalCreatePayload, GoalPriority } from '../types/goal';
import { EmptyState } from '../components/ui/EmptyState';
import {
  calculateDeadlineRisk,
  calculateGoalProgress,
  calculateOverallSummary,
  formatRelativeTime,
  getGoalNextAction,
} from '../utils/dashboardMetrics';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Progress } from '../components/ui/Progress';
import { Skeleton } from '../components/ui/Skeleton';
import { Alert } from '../components/ui/Alert';
import { Modal } from '../components/ui/Modal';
import { Input } from '../components/ui/Input';
import { APIError } from '../types/api';

export const DashboardPage: React.FC = () => {
  const { user } = useAuth();
  const queryClient = useQueryClient();

  // Filter state for active goals grid
  const [filterPriority, setFilterPriority] = useState<'all' | 'critical_high' | 'with_deadline'>('all');
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  // New Goal quick modal state
  const [newTitle, setNewTitle] = useState('');
  const [newObjective, setNewObjective] = useState('');
  const [newPriority, setNewPriority] = useState<GoalPriority>('medium');
  const [newDeadline, setNewDeadline] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  // 1. Fetch Goals
  const {
    data: goalsData,
    isLoading: isLoadingGoals,
    isError: isGoalsError,
    error: goalsError,
    refetch: refetchGoals,
    isFetching: isFetchingGoals,
  } = useQuery({
    queryKey: ['goals'],
    queryFn: () => goalService.listGoals({ limit: 100 }),
  });

  // 2. Fetch Recent Activity
  const {
    data: activityFeed = [],
    isLoading: isLoadingActivity,
    refetch: refetchActivity,
  } = useQuery({
    queryKey: ['dashboardActivity'],
    queryFn: () => activityService.getCombinedActivityFeed(),
  });

  // 3. Fetch Pending Permission Requests
  const {
    data: pendingRequests = [],
    refetch: refetchRequests,
  } = useQuery({
    queryKey: ['pendingPermissions'],
    queryFn: () => activityService.getPendingRequests(),
  });

  // Goal Mutations (Pause / Resume / Complete)
  const pauseMutation = useMutation({
    mutationFn: (goalId: string) => goalService.pauseGoal(goalId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['goals'] }),
  });

  const resumeMutation = useMutation({
    mutationFn: (goalId: string) => goalService.resumeGoal(goalId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['goals'] }),
  });

  const completeMutation = useMutation({
    mutationFn: (goalId: string) => goalService.completeGoal(goalId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['goals'] }),
  });

  // Permission Approvals Mutations
  const approveRequestMutation = useMutation({
    mutationFn: (reqId: string) => activityService.approvePermissionRequest(reqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pendingPermissions'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardActivity'] });
    },
  });

  const rejectRequestMutation = useMutation({
    mutationFn: (reqId: string) => activityService.rejectPermissionRequest(reqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pendingPermissions'] });
      queryClient.invalidateQueries({ queryKey: ['dashboardActivity'] });
    },
  });

  // Quick Create Goal Mutation
  const createMutation = useMutation({
    mutationFn: (payload: GoalCreatePayload) => goalService.createGoal(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goals'] });
      setIsCreateOpen(false);
      setNewTitle('');
      setNewObjective('');
      setNewPriority('medium');
      setNewDeadline('');
    },
    onError: (err: unknown) => {
      if (err instanceof APIError) {
        setFormError(err.message);
      } else {
        setFormError('Failed to create goal');
      }
    },
  });

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (newTitle.trim().length < 3) {
      setFormError('Title must be at least 3 characters');
      return;
    }
    if (newObjective.trim().length < 5) {
      setFormError('Objective must be at least 5 characters');
      return;
    }

    createMutation.mutate({
      title: newTitle.trim(),
      objective: newObjective.trim(),
      priority: newPriority,
      deadline: newDeadline ? new Date(newDeadline).toISOString() : null,
      success_criteria: [],
    });
  };

  // Derive all metrics purely from real backend data
  const goals: Goal[] = goalsData?.items || [];
  const summary = calculateOverallSummary(goals);

  // Active goals list
  const activeGoals = goals.filter((g) => g.status === 'active');

  // Filter active goals by selected pill
  const filteredActiveGoals = activeGoals.filter((g) => {
    if (filterPriority === 'critical_high') {
      return g.priority === 'critical' || g.priority === 'high';
    }
    if (filterPriority === 'with_deadline') {
      return Boolean(g.deadline);
    }
    return true;
  });

  // Manual refresh all
  const handleRefreshAll = () => {
    refetchGoals();
    refetchActivity();
    refetchRequests();
  };

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-12">
      {/* Network / Query Error State */}
      {isGoalsError && (
        <div className="p-5 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex flex-col sm:flex-row sm:items-center justify-between gap-4 animate-fade-in">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center shrink-0">
              <AlertTriangle className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white">Failed to sync command dashboard</h3>
              <p className="text-xs text-rose-300/80 mt-0.5">
                {goalsError instanceof Error ? goalsError.message : 'Unable to retrieve real-time goals telemetry.'}
              </p>
            </div>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshAll}
            leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
            className="shrink-0"
          >
            Retry Sync
          </Button>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 1. EXECUTIVE SITUATION BANNER ("Communicate Situation in Seconds")        */}
      {/* ========================================================================= */}
      <section
        aria-label="Executive Situation Summary"
        className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-slate-900 via-slate-900/95 to-slate-950 border border-slate-800 shadow-2xl p-6 sm:p-8"
      >
        <div className="relative z-10 space-y-6">
          {/* Header Row */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-6 border-b border-slate-800/80">
            <div className="space-y-1">
              <div className="flex items-center space-x-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-xs font-mono uppercase tracking-widest text-emerald-400 font-semibold">
                  Autonomous Command Status
                </span>
                {isFetchingGoals && (
                  <span className="text-[11px] text-slate-500 font-mono flex items-center space-x-1">
                    <RefreshCw className="w-3 h-3 animate-spin" />
                    <span>Syncing...</span>
                  </span>
                )}
              </div>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
                {user?.display_name || user?.email?.split('@')[0] || 'Operator'}&rsquo;s Command Dashboard
              </h1>
              <p className="text-xs sm:text-sm text-slate-400">
                Real-time operational awareness across long-horizon objectives, deadlines, and agent execution.
              </p>
            </div>

            <div className="flex items-center space-x-3 shrink-0">
              <button
                onClick={handleRefreshAll}
                className="p-2 rounded-lg bg-slate-800/60 hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-slate-700/60 transition-colors"
                title="Refresh dashboard data"
                aria-label="Refresh data"
              >
                <RefreshCw className={`w-4 h-4 ${isFetchingGoals ? 'animate-spin' : ''}`} />
              </button>
              <Button
                onClick={() => setIsCreateOpen(true)}
                leftIcon={<Plus className="w-4 h-4" />}
                size="sm"
              >
                New Goal
              </Button>
            </div>
          </div>

          {/* 4 Core Situational Indicators */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* 1. Active Goals Count & Highest Priority */}
            <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                <span className="uppercase tracking-wider">Active Objectives</span>
                <Target className="w-4 h-4 text-emerald-400" />
              </div>
              {isLoadingGoals ? (
                <Skeleton className="h-8 w-16" />
              ) : (
                <div className="flex items-baseline space-x-2">
                  <span className="text-3xl font-extrabold text-white font-mono">
                    {summary.activeGoalsCount}
                  </span>
                  <span className="text-xs text-slate-400">
                    of {goals.length} total
                  </span>
                </div>
              )}
              <div className="flex items-center space-x-1.5 pt-1 text-xs">
                <span className="text-slate-400">Max Priority:</span>
                {summary.highestPriority ? (
                  <Badge variant={summary.highestPriority}>{summary.highestPriority}</Badge>
                ) : (
                  <span className="text-slate-500 font-mono text-xs">None</span>
                )}
              </div>
            </div>

            {/* 2. Overall Progress */}
            <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                <span className="uppercase tracking-wider">Overall Progress</span>
                <CheckCircle2 className="w-4 h-4 text-teal-400" />
              </div>
              {isLoadingGoals ? (
                <Skeleton className="h-8 w-24" />
              ) : (
                <div className="space-y-1.5">
                  <div className="flex items-baseline space-x-2">
                    <span className="text-3xl font-extrabold text-white font-mono">
                      {summary.overallProgressPercent}%
                    </span>
                    <span className="text-xs text-slate-400 font-mono">
                      ({summary.completedMilestonesCount}/{summary.totalMilestonesCount} milestones)
                    </span>
                  </div>
                  <Progress value={summary.overallProgressPercent} size="sm" variant="gradient" />
                </div>
              )}
            </div>

            {/* 3. Nearest Deadline & Deadline Risk */}
            <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                <span className="uppercase tracking-wider">Nearest Deadline</span>
                <Clock className="w-4 h-4 text-amber-400" />
              </div>
              {isLoadingGoals ? (
                <Skeleton className="h-8 w-28" />
              ) : summary.nearestDeadline ? (
                <div>
                  <div className="text-sm font-bold text-white truncate" title={summary.nearestDeadline.goal.title}>
                    {summary.nearestDeadline.goal.title}
                  </div>
                  <div className="text-xs text-slate-300 font-mono mt-0.5">
                    {new Date(summary.nearestDeadline.goal.deadline!).toLocaleDateString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                    })}
                  </div>
                  <div className="mt-1">
                    <span
                      className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-mono font-medium border ${
                        summary.nearestDeadline.risk.level === 'critical'
                          ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                          : summary.nearestDeadline.risk.level === 'high'
                          ? 'bg-orange-500/10 text-orange-400 border-orange-500/30'
                          : summary.nearestDeadline.risk.level === 'medium'
                          ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                          : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                      }`}
                    >
                      {summary.nearestDeadline.risk.label}: {summary.nearestDeadline.risk.text}
                    </span>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-slate-500 italic mt-2">
                  No upcoming deadlines set
                </div>
              )}
            </div>

            {/* 4. Immediate Next Action */}
            <div className="p-4 rounded-xl bg-slate-950/60 border border-slate-800 space-y-2">
              <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                <span className="uppercase tracking-wider">Immediate Next Action</span>
                <Flame className="w-4 h-4 text-orange-400" />
              </div>
              {isLoadingGoals ? (
                <Skeleton className="h-8 w-full" />
              ) : summary.urgentNextAction ? (
                <div className="space-y-1">
                  <div className="text-xs text-slate-400 truncate">
                    For: <span className="text-slate-200 font-medium">{summary.urgentNextAction.goal.title}</span>
                  </div>
                  <div className="text-sm font-semibold text-emerald-300 line-clamp-2">
                    &bull; {summary.urgentNextAction.action.title}
                  </div>
                  <div className="text-[11px] text-slate-500 capitalize">
                    Status: <span className="font-mono text-slate-400">{summary.urgentNextAction.action.status.replace('_', ' ')}</span>
                  </div>
                </div>
              ) : (
                <div className="text-xs text-slate-500 italic mt-2">
                  {goals.length === 0 ? 'Create a goal to begin' : 'All current milestones resolved'}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Ambient subtle decorative light */}
        <div className="absolute right-0 top-0 -mt-10 -mr-10 w-96 h-96 bg-emerald-500/5 rounded-full blur-3xl pointer-events-none" />
      </section>

      {/* ========================================================================= */}
      {/* 2. PENDING PERMISSION REQUESTS BANNER (Human-in-the-Loop)                  */}
      {/* ========================================================================= */}
      {pendingRequests.length > 0 && (
        <section aria-label="Pending Approvals Alert" className="animate-in slide-in-from-top-2">
          <div className="rounded-xl border border-amber-500/40 bg-amber-950/20 p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400">
                  <ShieldAlert className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-amber-200">
                    Action Authorization Required ({pendingRequests.length})
                  </h3>
                  <p className="text-xs text-amber-300/80">
                    The autonomous agent is requesting human clearance before executing protected actions.
                  </p>
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {pendingRequests.map((req) => (
                <div
                  key={req.id}
                  className="bg-slate-900/90 border border-slate-800 rounded-lg p-4 space-y-3"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <span className="text-xs font-mono font-semibold uppercase text-amber-400 bg-amber-950/60 px-2 py-0.5 rounded border border-amber-800/60">
                        {req.action}
                      </span>
                      <p className="text-xs text-slate-300 mt-2 font-medium">
                        {req.reason}
                      </p>
                    </div>
                    <Badge variant="warning">{req.risk_level}</Badge>
                  </div>

                  <div className="flex items-center justify-end space-x-2 pt-2 border-t border-slate-800">
                    <Button
                      variant="outline"
                      size="sm"
                      isLoading={rejectRequestMutation.isPending}
                      onClick={() => rejectRequestMutation.mutate(req.id)}
                    >
                      Reject
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      isLoading={approveRequestMutation.isPending}
                      onClick={() => approveRequestMutation.mutate(req.id)}
                      leftIcon={<ShieldCheck className="w-3.5 h-3.5" />}
                    >
                      Approve
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* ========================================================================= */}
      {/* 3. ACTIVE GOALS WORKSPACE & BREAKDOWN                                    */}
      {/* ========================================================================= */}
      <section aria-label="Active Goals Operational View" className="space-y-4">
        {/* Section Title & Filter Tabs */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center space-x-2">
              <Target className="w-5 h-5 text-emerald-400" />
              <span>Active Goals &amp; Execution State</span>
            </h2>
            <p className="text-xs text-slate-400">
              Real-time progress, upcoming milestones, and deadline risks for running goals
            </p>
          </div>

          <div className="flex items-center space-x-2">
            <div className="flex items-center space-x-1 bg-slate-900 p-1 rounded-lg border border-slate-800 text-xs">
              <button
                onClick={() => setFilterPriority('all')}
                className={`px-2.5 py-1 rounded font-medium transition-colors ${
                  filterPriority === 'all'
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                All Active ({activeGoals.length})
              </button>
              <button
                onClick={() => setFilterPriority('critical_high')}
                className={`px-2.5 py-1 rounded font-medium transition-colors ${
                  filterPriority === 'critical_high'
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                Critical &amp; High
              </button>
              <button
                onClick={() => setFilterPriority('with_deadline')}
                className={`px-2.5 py-1 rounded font-medium transition-colors ${
                  filterPriority === 'with_deadline'
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                With Deadlines
              </button>
            </div>

            <Link
              to="/goals"
              className="text-xs text-emerald-400 hover:text-emerald-300 font-medium inline-flex items-center space-x-1 pl-2"
            >
              <span>Manage All</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>

        {/* Error Handling State */}
        {isGoalsError && (
          <Alert variant="error" title="Failed to load goals" onDismiss={() => refetchGoals()}>
            {goalsError instanceof Error ? goalsError.message : 'Could not reach backend API.'}
          </Alert>
        )}

        {/* Loading Skeletons */}
        {isLoadingGoals ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="p-6 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4"
              >
                <div className="flex justify-between">
                  <Skeleton className="h-5 w-32" />
                  <Skeleton className="h-5 w-16" />
                </div>
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-2 w-full" />
                <div className="flex justify-between pt-2">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-4 w-20" />
                </div>
              </div>
            ))}
          </div>
        ) : filteredActiveGoals.length === 0 ? (
          /* Empty State */
          goals.length === 0 ? (
            <EmptyState
              icon={Target}
              title="No Goals Defined Yet"
              description="Start by creating your first autonomous mission. LifeThread will track deadlines, priorities, and agent execution."
              action={{
                label: 'Create New Goal',
                icon: Plus,
                onClick: () => setIsCreateOpen(true),
              }}
            />
          ) : (
            <EmptyState
              icon={Target}
              title="No Goals Match Active Filter"
              description="All defined goals are currently paused, archived, or completed. Reset filter or define a new goal."
              action={{
                label: 'Reset Filter',
                onClick: () => setFilterPriority('all'),
              }}
              secondaryAction={{
                label: 'Create New Goal',
                onClick: () => setIsCreateOpen(true),
              }}
            />
          )
        ) : (
          /* Active Goals Grid */
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {filteredActiveGoals.map((goal) => {
              const progress = calculateGoalProgress(goal);
              const nextAction = getGoalNextAction(goal);
              const deadlineRisk = calculateDeadlineRisk(
                goal.deadline,
                progress.progressPercent,
                goal.status
              );

              return (
                <div
                  key={goal.id}
                  className="rounded-2xl border border-slate-800 bg-slate-900/60 hover:bg-slate-900/80 transition-all duration-200 p-5 flex flex-col justify-between space-y-4 shadow-lg group hover:border-slate-700"
                >
                  {/* Card Header */}
                  <div className="space-y-2.5">
                    <div className="flex items-start justify-between gap-2">
                      <Badge variant={goal.priority}>{goal.priority} Priority</Badge>
                      <Badge variant={goal.status}>{goal.status}</Badge>
                    </div>

                    <Link to={`/goals/${goal.id}`} className="block group">
                      <h3 className="font-bold text-white text-base group-hover:text-emerald-400 transition-colors line-clamp-1">
                        {goal.title}
                      </h3>
                      <p className="text-xs text-slate-400 line-clamp-2 mt-1 leading-relaxed">
                        {goal.objective}
                      </p>
                    </Link>
                  </div>

                  {/* Progress Section */}
                  <div className="space-y-1.5 pt-2 border-t border-slate-800/60">
                    <div className="flex items-center justify-between text-xs font-mono">
                      <span className="text-slate-400">Progress</span>
                      <span className="text-emerald-400 font-semibold">
                        {progress.progressPercent}%
                        {progress.hasMilestones && (
                          <span className="text-slate-500 font-normal ml-1">
                            ({progress.completedMilestones}/{progress.totalMilestones})
                          </span>
                        )}
                      </span>
                    </div>
                    <Progress
                      value={progress.progressPercent}
                      size="sm"
                      variant={
                        progress.progressPercent >= 100
                          ? 'emerald'
                          : progress.progressPercent > 50
                          ? 'gradient'
                          : 'blue'
                      }
                    />
                  </div>

                  {/* Next Action Box */}
                  <div className="p-3 rounded-xl bg-slate-950/70 border border-slate-800/80 space-y-1">
                    <div className="text-[10px] uppercase font-mono tracking-wider text-slate-400 flex items-center justify-between">
                      <span>Next Action</span>
                      {nextAction.status !== 'none' && (
                        <span
                          className={`text-[9px] px-1.5 py-0.2 rounded font-mono ${
                            nextAction.status === 'in_progress'
                              ? 'bg-blue-500/20 text-blue-400'
                              : 'bg-slate-800 text-slate-400'
                          }`}
                        >
                          {nextAction.status.replace('_', ' ')}
                        </span>
                      )}
                    </div>
                    <div className="text-xs font-medium text-slate-200 line-clamp-2">
                      {nextAction.title}
                    </div>
                  </div>

                  {/* Deadline & Deadline Risk */}
                  <div className="space-y-1 text-xs pt-1">
                    <div className="flex items-center justify-between text-slate-400">
                      <span className="flex items-center space-x-1.5">
                        <Calendar className="w-3.5 h-3.5 text-slate-500" />
                        <span>Deadline:</span>
                      </span>
                      <span className="font-mono text-slate-300">
                        {goal.deadline
                          ? new Date(goal.deadline).toLocaleDateString(undefined, {
                              month: 'short',
                              day: 'numeric',
                            })
                          : 'None'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between">
                      <span className="text-slate-400">Risk:</span>
                      <span
                        className={`text-[11px] font-mono px-2 py-0.5 rounded border ${
                          deadlineRisk.level === 'critical'
                            ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                            : deadlineRisk.level === 'high'
                            ? 'bg-orange-500/10 text-orange-400 border-orange-500/30'
                            : deadlineRisk.level === 'medium'
                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                            : deadlineRisk.level === 'none'
                            ? 'bg-slate-800/50 text-slate-400 border-slate-700/40'
                            : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                        }`}
                      >
                        {deadlineRisk.label}
                      </span>
                    </div>
                  </div>

                  {/* Quick Card Action Buttons */}
                  <div className="pt-3 border-t border-slate-800/60 flex items-center justify-between">
                    <Link
                      to={`/goals/${goal.id}`}
                      className="text-xs text-slate-400 hover:text-white inline-flex items-center space-x-1"
                    >
                      <span>Details</span>
                      <ExternalLink className="w-3 h-3" />
                    </Link>

                    <div className="flex items-center space-x-1.5">
                      {goal.status === 'paused' ? (
                        <button
                          onClick={() => resumeMutation.mutate(goal.id)}
                          disabled={resumeMutation.isPending}
                          className="px-2 py-1 rounded bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 text-xs font-medium flex items-center space-x-1 transition-colors"
                          title="Resume Goal"
                          aria-label="Resume Goal"
                        >
                          <Play className="w-3 h-3 text-emerald-400" />
                          <span>Resume</span>
                        </button>
                      ) : (
                        <button
                          onClick={() => pauseMutation.mutate(goal.id)}
                          disabled={pauseMutation.isPending}
                          className="px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium flex items-center space-x-1 transition-colors"
                          title="Pause Goal"
                          aria-label="Pause Goal"
                        >
                          <Pause className="w-3 h-3 text-amber-400" />
                          <span>Pause</span>
                        </button>
                      )}

                      <button
                        onClick={() => completeMutation.mutate(goal.id)}
                        disabled={completeMutation.isPending}
                        className="px-2 py-1 rounded bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 border border-emerald-500/30 text-xs font-medium flex items-center space-x-1 transition-colors"
                        title="Complete Goal"
                        aria-label="Complete Goal"
                      >
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Complete</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ========================================================================= */}
      {/* 4. RECENT AGENT ACTIVITY FEED (Real Learning Memories & Approvals)        */}
      {/* ========================================================================= */}
      <section aria-label="Recent Agent Activity" className="space-y-4 pt-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center space-x-2">
              <ActivityCircleIcon className="w-5 h-5 text-emerald-400" />
              <span>Recent Autonomous Agent Activity</span>
            </h2>
            <p className="text-xs text-slate-400">
              Live audit trail of agent learning loops, insights, and human permission decisions
            </p>
          </div>

          <div className="flex items-center space-x-3">
            <Link
              to="/activity"
              className="text-xs text-emerald-400 hover:text-emerald-300 flex items-center space-x-1 font-medium bg-emerald-950/40 hover:bg-emerald-900/50 border border-emerald-800/60 px-2.5 py-1.5 rounded-lg transition-colors"
              title="View full agent execution traces"
            >
              <span>Full Traces</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
            <button
              onClick={() => refetchActivity()}
              className="text-xs text-slate-400 hover:text-slate-200 flex items-center space-x-1 font-mono px-2 py-1.5 rounded-lg hover:bg-slate-800 transition-colors"
              aria-label="Refresh activity feed"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {isLoadingActivity ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 space-y-2"
              >
                <div className="flex justify-between">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-4 w-16" />
                </div>
                <Skeleton className="h-3 w-full" />
              </div>
            ))}
          </div>
        ) : activityFeed.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            title="No Agent Activity Logged Yet"
            description="As the LifeThread agent decomposes tasks, executes workflows, records learning memories, or requests action approvals, events will populate here."
          />
        ) : (
          <div className="rounded-2xl border border-slate-800 bg-slate-900/50 divide-y divide-slate-800/60 overflow-hidden shadow-lg">
            {activityFeed.slice(0, 10).map((item) => (
              <div
                key={item.id}
                className="p-4 hover:bg-slate-900/80 transition-colors flex items-start space-x-3.5"
              >
                <div className="mt-0.5 shrink-0">
                  {item.type === 'learning_memory' ? (
                    <div className="w-8 h-8 rounded-lg bg-teal-500/10 border border-teal-500/20 flex items-center justify-center text-teal-400">
                      <Sparkles className="w-4 h-4" />
                    </div>
                  ) : item.type === 'approval' ? (
                    <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
                      <ShieldCheck className="w-4 h-4" />
                    </div>
                  ) : (
                    <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                      <CheckCircle2 className="w-4 h-4" />
                    </div>
                  )}
                </div>

                <div className="flex-1 min-w-0 space-y-1">
                  <div className="flex items-baseline justify-between gap-2">
                    <h4 className="text-xs sm:text-sm font-semibold text-white truncate">
                      {item.title}
                    </h4>
                    <span className="text-[11px] font-mono text-slate-500 shrink-0">
                      {formatRelativeTime(item.timestamp)}
                    </span>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed">
                    {item.description}
                  </p>

                  {item.badge && (
                    <div className="pt-0.5">
                      <span
                        className={`inline-block text-[10px] font-mono px-2 py-0.2 rounded border ${
                          item.badgeVariant === 'success'
                            ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                            : item.badgeVariant === 'warning'
                            ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                            : 'bg-slate-800 text-slate-400 border-slate-700'
                        }`}
                      >
                        {item.badge}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ========================================================================= */}
      {/* 5. QUICK NEW GOAL MODAL                                                   */}
      {/* ========================================================================= */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Create New Objective"
        description="Every value entered will be validated and tracked in your real-time dashboard."
        maxWidth="lg"
      >
        <form onSubmit={handleCreateSubmit} className="space-y-4 pt-1">
          {formError && (
            <Alert variant="error" title="Input Error" onDismiss={() => setFormError(null)}>
              {formError}
            </Alert>
          )}

          <Input
            id="modalGoalTitle"
            label="Goal Title"
            placeholder="e.g. Master Distributed Systems"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            required
            helperText="Minimum 3 characters"
          />

          <div className="space-y-1.5">
            <label
              htmlFor="modalGoalObjective"
              className="block text-xs font-medium uppercase tracking-wider text-slate-300"
            >
              Primary Objective
            </label>
            <textarea
              id="modalGoalObjective"
              rows={3}
              value={newObjective}
              onChange={(e) => setNewObjective(e.target.value)}
              required
              placeholder="e.g. Build consensus engine, run chaos tests, and benchmark latency"
              className="w-full bg-slate-900 border border-slate-800 text-slate-100 placeholder-slate-500 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
            <p className="text-xs text-slate-500">Minimum 5 characters</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label
                htmlFor="modalGoalPriority"
                className="block text-xs font-medium uppercase tracking-wider text-slate-300"
              >
                Priority Rank
              </label>
              <select
                id="modalGoalPriority"
                value={newPriority}
                onChange={(e) => setNewPriority(e.target.value as GoalPriority)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>

            <Input
              id="modalGoalDeadline"
              type="datetime-local"
              label="Target Deadline"
              value={newDeadline}
              onChange={(e) => setNewDeadline(e.target.value)}
            />
          </div>

          <div className="flex items-center justify-end space-x-3 pt-4 border-t border-slate-800">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setIsCreateOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              isLoading={createMutation.isPending}
              leftIcon={<Plus className="w-4 h-4" />}
            >
              Create Goal
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};

// Reusable micro-component for Activity Section Icon
const ActivityCircleIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
  </svg>
);
