import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ArrowRight,
  Calendar,
  CheckCircle2,
  Clock,
  Edit3,
  Flame,
  GitBranch,
  History,
  Layers,
  ListChecks,
  Network,
  Pause,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Trash2,
  TrendingUp,
} from 'lucide-react';
import { goalService } from '../services/goalService';
import { GoalPriority } from '../types/goal';
import { Task, TaskStatus, TaskUpdatePayload } from '../types/task';
import {
  calculateDeadlineRisk,
  calculateGoalProgress,
  formatRelativeTime,
  getGoalNextAction,
} from '../utils/dashboardMetrics';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Progress } from '../components/ui/Progress';
import { Card, CardContent } from '../components/ui/Card';
import { Skeleton } from '../components/ui/Skeleton';
import { Alert } from '../components/ui/Alert';
import { Modal } from '../components/ui/Modal';
import { Input } from '../components/ui/Input';
import { EmptyState } from '../components/ui/EmptyState';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { APIError } from '../types/api';
import { ReplanningDiffViewer } from '../components/replanning/ReplanningDiffViewer';

type TabType = 'overview' | 'tasks' | 'dependencies' | 'timeline' | 'risk' | 'versions' | 'replanning';

export const GoalDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const goalId = id!;

  const [activeTab, setActiveTab] = useState<TabType>('overview');

  // Task edit modal state
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [taskTitle, setTaskTitle] = useState('');
  const [taskDescription, setTaskDescription] = useState('');
  const [taskPriority, setTaskPriority] = useState<GoalPriority>('medium');
  const [taskStatus, setTaskStatus] = useState<TaskStatus>('PENDING');
  const [taskEstMinutes, setTaskEstMinutes] = useState(60);
  const [taskError, setTaskError] = useState<string | null>(null);

  // Selected historical plan version modal state
  const [selectedPlanVersion, setSelectedPlanVersion] = useState<number | null>(null);

  // Goal deletion confirmation state
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);

  // 1. Fetch Goal
  const {
    data: goal,
    isLoading: isLoadingGoal,
    isError: isGoalError,
    error: goalError,
    refetch: refetchGoal,
  } = useQuery({
    queryKey: ['goal', goalId],
    queryFn: () => goalService.getGoal(goalId),
    enabled: Boolean(goalId),
  });

  // 2. Fetch Tasks
  const {
    data: tasksData,
    isLoading: isLoadingTasks,
  } = useQuery({
    queryKey: ['goalTasks', goalId],
    queryFn: () => goalService.getTasks(goalId),
    enabled: Boolean(goalId),
  });

  // 3. Fetch Dependencies Graph
  const {
    data: dependencyGraph,
    isLoading: isLoadingDependencies,
  } = useQuery({
    queryKey: ['goalDependencies', goalId],
    queryFn: () => goalService.getDependencies(goalId),
    enabled: Boolean(goalId),
  });

  // 4. Fetch Active Execution Plan (Timeline)
  const {
    data: activePlan,
    isLoading: isLoadingPlan,
  } = useQuery({
    queryKey: ['goalActivePlan', goalId],
    queryFn: () => goalService.getActivePlan(goalId),
    enabled: Boolean(goalId),
    retry: false, // may not have generated plan yet
  });

  // 5. Fetch Plan Versions History
  const {
    data: planVersionsData,
    isLoading: isLoadingVersions,
  } = useQuery({
    queryKey: ['goalPlans', goalId],
    queryFn: () => goalService.getPlans(goalId),
    enabled: Boolean(goalId),
    retry: false,
  });

  // 6. Fetch / Run Goal Risk Evaluation
  const {
    data: evaluation,
    isLoading: isLoadingEvaluation,
    refetch: refetchEvaluation,
    isFetching: isFetchingEvaluation,
  } = useQuery({
    queryKey: ['goalEvaluation', goalId],
    queryFn: () => goalService.evaluateGoal(goalId),
    enabled: Boolean(goalId),
    retry: false,
  });

  // Fetch specific historical plan version if modal open
  const {
    data: historicalPlanDetail,
    isLoading: isLoadingHistoricalPlan,
  } = useQuery({
    queryKey: ['goalPlanVersion', goalId, selectedPlanVersion],
    queryFn: () => goalService.getPlanByVersion(goalId, selectedPlanVersion!),
    enabled: Boolean(goalId && selectedPlanVersion !== null),
  });

  // ================= MUTATIONS =================

  // Goal Priority change
  const priorityMutation = useMutation({
    mutationFn: (newPriority: GoalPriority) =>
      goalService.updateGoal(goalId, { priority: newPriority }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goal', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goals'] });
    },
  });

  // Goal Lifecycle (Pause / Resume / Complete)
  const pauseMutation = useMutation({
    mutationFn: () => goalService.pauseGoal(goalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goal', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goals'] });
    },
  });

  const resumeMutation = useMutation({
    mutationFn: () => goalService.resumeGoal(goalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goal', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goals'] });
    },
  });

  const completeGoalMutation = useMutation({
    mutationFn: () => goalService.completeGoal(goalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goal', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goals'] });
    },
  });

  const deleteGoalMutation = useMutation({
    mutationFn: () => goalService.deleteGoal(goalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goals'] });
      navigate('/goals');
    },
  });

  // Task Mutations (Complete & Update)
  const completeTaskMutation = useMutation({
    mutationFn: (taskId: string) => goalService.completeTask(goalId, taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goalTasks', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goal', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goalDependencies', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goalEvaluation', goalId] });
    },
  });

  const updateTaskMutation = useMutation({
    mutationFn: ({ taskId, payload }: { taskId: string; payload: TaskUpdatePayload }) =>
      goalService.updateTask(goalId, taskId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goalTasks', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goal', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goalDependencies', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goalEvaluation', goalId] });
      setEditingTask(null);
    },
    onError: (err: unknown) => {
      if (err instanceof APIError) {
        setTaskError(err.message);
      } else {
        setTaskError('Failed to update task');
      }
    },
  });

  // Generate Plan Mutation
  const generatePlanMutation = useMutation({
    mutationFn: () => goalService.generatePlan(goalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goalActivePlan', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goalPlans', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goalEvaluation', goalId] });
    },
  });

  // Decompose Goal Mutation
  const decomposeMutation = useMutation({
    mutationFn: () => goalService.decomposeGoal(goalId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goalTasks', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goal', goalId] });
      queryClient.invalidateQueries({ queryKey: ['goalDependencies', goalId] });
    },
  });

  // Handlers for task edit
  const openEditTask = (task: Task) => {
    setEditingTask(task);
    setTaskTitle(task.title);
    setTaskDescription(task.description || '');
    setTaskPriority(task.priority);
    setTaskStatus(task.status);
    setTaskEstMinutes(task.estimated_minutes || 60);
    setTaskError(null);
  };

  const handleUpdateTaskSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingTask) return;
    if (taskTitle.trim().length === 0) {
      setTaskError('Task title cannot be empty');
      return;
    }

    updateTaskMutation.mutate({
      taskId: editingTask.id,
      payload: {
        title: taskTitle.trim(),
        description: taskDescription.trim() || null,
        priority: taskPriority,
        status: taskStatus,
        estimated_minutes: taskEstMinutes,
      },
    });
  };

  // Loading state
  if (isLoadingGoal) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-9 w-36" />
        <div className="p-8 rounded-2xl border border-slate-800 bg-slate-900/40 space-y-4">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 pt-4">
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
            <Skeleton className="h-20" />
          </div>
        </div>
      </div>
    );
  }

  // Error state
  if (isGoalError || !goal) {
    return (
      <div className="space-y-6">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate('/goals')}
          leftIcon={<ArrowLeft className="w-4 h-4" />}
        >
          Back to Goals
        </Button>
        <Alert variant="error" title="Goal Not Found" onDismiss={() => refetchGoal()}>
          {goalError instanceof Error ? goalError.message : 'Could not find requested goal record'}
        </Alert>
      </div>
    );
  }

  // Derived real progress and next action
  const progressInfo = calculateGoalProgress(goal);
  const tasks = tasksData?.items || [];
  const completedTasksCount = tasks.filter((t) => t.status === 'COMPLETED').length;
  const taskProgressPercent = tasks.length > 0 ? Math.round((completedTasksCount / tasks.length) * 100) : 0;
  const combinedProgressPercent = tasks.length > 0 ? taskProgressPercent : progressInfo.progressPercent;

  // Next action determination: check task in progress first, then task pending, then milestone
  let nextActionTitle = 'No pending actions';
  let nextActionType: 'task' | 'milestone' | 'none' = 'none';
  const inProgressTask = tasks.find((t) => t.status === 'IN_PROGRESS');
  const pendingTask = tasks.find((t) => t.status === 'PENDING');
  const milestoneAction = getGoalNextAction(goal);

  if (inProgressTask) {
    nextActionTitle = inProgressTask.title;
    nextActionType = 'task';
  } else if (pendingTask) {
    nextActionTitle = pendingTask.title;
    nextActionType = 'task';
  } else if (milestoneAction.isDefined && milestoneAction.status !== 'none') {
    nextActionTitle = milestoneAction.title;
    nextActionType = 'milestone';
  }

  // Deadline Risk calculation
  const deadlineRisk = calculateDeadlineRisk(goal.deadline, combinedProgressPercent, goal.status);
  const planVersions = planVersionsData?.items || [];

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-16">
      {/* ========================================================================= */}
      {/* 1. TOP NAVIGATION & EXECUTIVE ACTIONS                                      */}
      {/* ========================================================================= */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate('/goals')}
          leftIcon={<ArrowLeft className="w-4 h-4" />}
        >
          Back to Goals
        </Button>

        {/* Lifecycle Action Buttons */}
        <div className="flex items-center space-x-2">
          {goal.status === 'active' ? (
            <Button
              variant="secondary"
              size="sm"
              isLoading={pauseMutation.isPending}
              onClick={() => pauseMutation.mutate()}
              leftIcon={<Pause className="w-3.5 h-3.5 text-amber-400" />}
            >
              Pause Goal
            </Button>
          ) : goal.status === 'paused' ? (
            <Button
              variant="secondary"
              size="sm"
              isLoading={resumeMutation.isPending}
              onClick={() => resumeMutation.mutate()}
              leftIcon={<Play className="w-3.5 h-3.5 text-emerald-400" />}
            >
              Resume Goal
            </Button>
          ) : null}

          {goal.status !== 'completed' && (
            <Button
              variant="primary"
              size="sm"
              isLoading={completeGoalMutation.isPending}
              onClick={() => completeGoalMutation.mutate()}
              leftIcon={<CheckCircle2 className="w-3.5 h-3.5" />}
            >
              Mark Completed
            </Button>
          )}

          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsDeleteConfirmOpen(true)}
            className="text-slate-400 hover:text-rose-400 hover:bg-rose-500/10"
            leftIcon={<Trash2 className="w-3.5 h-3.5" />}
            title="Delete Goal"
          >
            Delete
          </Button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 2. GOAL HEADER & SUMMARY CARD                                             */}
      {/* ========================================================================= */}
      <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-6 sm:p-8 space-y-6 shadow-xl relative overflow-hidden">
        <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6 pb-6 border-b border-slate-800">
          <div className="space-y-3 max-w-3xl">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={goal.status}>{goal.status}</Badge>

              {/* Interactive Priority Selector */}
              <div className="flex items-center space-x-1.5 bg-slate-950 px-2.5 py-1 rounded-full border border-slate-800">
                <span className="text-[11px] font-mono text-slate-400 uppercase">Priority:</span>
                <select
                  value={goal.priority}
                  disabled={priorityMutation.isPending}
                  onChange={(e) => priorityMutation.mutate(e.target.value as GoalPriority)}
                  className="bg-transparent text-xs font-semibold text-white uppercase focus:outline-none cursor-pointer"
                  title="Change goal priority rank"
                  aria-label="Change priority"
                >
                  <option value="low" className="bg-slate-900 text-slate-300">LOW</option>
                  <option value="medium" className="bg-slate-900 text-amber-400">MEDIUM</option>
                  <option value="high" className="bg-slate-900 text-orange-400">HIGH</option>
                  <option value="critical" className="bg-slate-900 text-rose-400">CRITICAL</option>
                </select>
                {priorityMutation.isPending && (
                  <RefreshCw className="w-3 h-3 text-slate-400 animate-spin" />
                )}
              </div>
            </div>

            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              {goal.title}
            </h1>
            <p className="text-sm text-slate-300 leading-relaxed">
              {goal.objective}
            </p>
          </div>

          <div className="text-right text-xs font-mono text-slate-400 space-y-1.5 shrink-0">
            <div>Goal ID: <span className="text-slate-300">{goal.id.substring(0, 8)}...</span></div>
            <div>Created: {new Date(goal.created_at).toLocaleDateString()}</div>
            <div>Updated: {new Date(goal.updated_at).toLocaleDateString()}</div>
          </div>
        </div>

        {/* Focus Next Action Banner */}
        <div className="p-4 rounded-xl bg-gradient-to-r from-emerald-950/40 via-slate-900 to-slate-950 border border-emerald-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start space-x-3">
            <div className="p-2 rounded-lg bg-emerald-500/20 text-emerald-400 mt-0.5 shrink-0">
              <Flame className="w-5 h-5" />
            </div>
            <div>
              <div className="text-xs uppercase font-mono tracking-wider text-emerald-400 font-semibold flex items-center space-x-2">
                <span>Immediate Next Action</span>
                {nextActionType !== 'none' && (
                  <span className="text-[10px] px-1.5 py-0.2 rounded bg-slate-800 text-slate-300">
                    Source: {nextActionType}
                  </span>
                )}
              </div>
              <p className="text-sm sm:text-base font-semibold text-white mt-0.5">
                {nextActionTitle}
              </p>
            </div>
          </div>

          {tasks.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setActiveTab('tasks')}
              rightIcon={<ArrowRight className="w-3.5 h-3.5" />}
            >
              View in Tasks
            </Button>
          )}
        </div>

        {/* 4 Quantitative Operational Ribbons */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-2">
          {/* Progress */}
          <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-2">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400">
              <span className="uppercase">Overall Progress</span>
              <TrendingUp className="w-4 h-4 text-emerald-400" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-bold font-mono text-white">
                {combinedProgressPercent}%
              </span>
              <span className="text-xs text-slate-400 font-mono">
                {tasks.length > 0
                  ? `${completedTasksCount}/${tasks.length} tasks`
                  : `${progressInfo.completedMilestones}/${progressInfo.totalMilestones} milestones`}
              </span>
            </div>
            <Progress value={combinedProgressPercent} size="sm" variant="gradient" />
          </div>

          {/* Target Deadline */}
          <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-1.5">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400">
              <span className="uppercase">Target Deadline</span>
              <Calendar className="w-4 h-4 text-blue-400" />
            </div>
            <div className="text-sm font-semibold text-white font-mono">
              {goal.deadline
                ? new Date(goal.deadline).toLocaleDateString(undefined, {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                  })
                : 'No deadline set'}
            </div>
            <div className="text-xs text-slate-400">
              {deadlineRisk.text}
            </div>
          </div>

          {/* Deadline Risk Tier */}
          <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-1.5">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400">
              <span className="uppercase">Deadline Risk</span>
              <Clock className="w-4 h-4 text-amber-400" />
            </div>
            <div className="flex items-center space-x-2">
              <span
                className={`inline-block px-2.5 py-0.5 rounded text-xs font-mono font-semibold border ${
                  deadlineRisk.level === 'critical'
                    ? 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                    : deadlineRisk.level === 'high'
                    ? 'bg-orange-500/10 text-orange-400 border-orange-500/30'
                    : deadlineRisk.level === 'medium'
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                    : deadlineRisk.level === 'none'
                    ? 'bg-slate-800 text-slate-400 border-slate-700'
                    : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                }`}
              >
                {deadlineRisk.label}
              </span>
            </div>
            <div className="text-[11px] text-slate-500">
              {evaluation?.is_moving_forward ? 'Actively moving forward' : 'Pace under analysis'}
            </div>
          </div>

          {/* Plan Revisions */}
          <div className="p-4 rounded-xl bg-slate-950/70 border border-slate-800 space-y-1.5">
            <div className="flex items-center justify-between text-xs font-mono text-slate-400">
              <span className="uppercase">Plan Revisions</span>
              <History className="w-4 h-4 text-purple-400" />
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-2xl font-bold font-mono text-white">
                {planVersions.length > 0 ? planVersions.length : activePlan ? 1 : 0}
              </span>
              <span className="text-xs text-slate-400">
                {activePlan ? `(Active v${activePlan.version})` : 'Unplanned'}
              </span>
            </div>
            <div className="flex items-center space-x-3 pt-0.5">
              <button
                onClick={() => setActiveTab('versions')}
                className="text-xs text-slate-400 hover:text-white font-mono"
              >
                History &rarr;
              </button>
              {(planVersions.length > 1 || (activePlan && activePlan.version > 1)) && (
                <button
                  onClick={() => setActiveTab('replanning')}
                  className="text-[11px] text-emerald-400 hover:text-emerald-300 font-mono font-semibold flex items-center space-x-1"
                >
                  <Sparkles className="w-3 h-3" />
                  <span>Plan Changed Diff</span>
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 3. WORKSPACE NAVIGATION TABS                                              */}
      {/* ========================================================================= */}
      <div className="border-b border-slate-800 overflow-x-auto scrollbar-none">
        <nav className="flex space-x-2 sm:space-x-4 min-w-max pb-px" aria-label="Goal Workspace Tabs">
          {[
            { id: 'overview', label: 'Overview & Milestones', icon: <Layers className="w-4 h-4" /> },
            { id: 'tasks', label: `Tasks (${tasks.length})`, icon: <ListChecks className="w-4 h-4" /> },
            { id: 'dependencies', label: 'Dependencies DAG', icon: <Network className="w-4 h-4" /> },
            { id: 'timeline', label: 'Timeline & Schedule', icon: <Calendar className="w-4 h-4" /> },
            { id: 'risk', label: 'Risk & Diagnosis', icon: <ShieldAlert className="w-4 h-4" /> },
            { id: 'versions', label: `Plan Versions (${planVersions.length})`, icon: <History className="w-4 h-4" /> },
            { id: 'replanning', label: 'Replanning Diff', icon: <GitBranch className="w-4 h-4" /> },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as TabType)}
              className={`flex items-center space-x-2 py-3 px-3.5 border-b-2 font-medium text-sm transition-colors whitespace-nowrap ${
                activeTab === tab.id
                  ? 'border-emerald-400 text-emerald-400 bg-slate-900/40 rounded-t-lg'
                  : 'border-transparent text-slate-400 hover:text-slate-200 hover:border-slate-700'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: OVERVIEW & MILESTONES                                              */}
      {/* ========================================================================= */}
      {activeTab === 'overview' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          {/* Description Card */}
          {goal.description && (
            <Card>
              <CardContent className="pt-6 space-y-2">
                <h3 className="text-xs uppercase font-mono tracking-wider text-slate-400">
                  Detailed Guidance &amp; Description
                </h3>
                <p className="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">
                  {goal.description}
                </p>
              </CardContent>
            </Card>
          )}

          {/* Progressive Milestones */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-bold text-white flex items-center space-x-2">
                  <Layers className="w-5 h-5 text-emerald-400" />
                  <span>Progressive Phase Milestones ({goal.milestones?.length || 0})</span>
                </h3>
                <p className="text-xs text-slate-400">
                  Sequential target checkpoints required to achieve this goal
                </p>
              </div>
            </div>

            {(!goal.milestones || goal.milestones.length === 0) ? (
              <EmptyState
                icon={Layers}
                title="No Milestones Registered Yet"
                description="Decompose this goal to automatically synthesize progressive phase milestones and executable tasks."
                action={{
                  label: decomposeMutation.isPending ? 'Decomposing...' : 'Decompose Goal via Agent',
                  icon: Sparkles,
                  onClick: () => decomposeMutation.mutate(),
                }}
              />
            ) : (
              <div className="space-y-3">
                {[...goal.milestones]
                  .sort((a, b) => a.order_index - b.order_index)
                  .map((milestone, idx) => (
                    <div
                      key={milestone.id}
                      className="p-4 rounded-xl border border-slate-800 bg-slate-900/60 flex items-start space-x-4 hover:border-slate-700 transition-colors"
                    >
                      <div className="w-7 h-7 rounded-full bg-slate-800 border border-slate-700 flex items-center justify-center text-xs font-mono font-bold text-emerald-400 shrink-0">
                        {idx + 1}
                      </div>

                      <div className="flex-1 min-w-0 space-y-1">
                        <div className="flex items-baseline justify-between gap-2">
                          <h4 className="text-sm font-semibold text-white">
                            {milestone.title}
                          </h4>
                          <Badge variant={milestone.status === 'completed' ? 'completed' : milestone.status === 'in_progress' ? 'active' : 'default'}>
                            {milestone.status.replace('_', ' ')}
                          </Badge>
                        </div>
                        {milestone.description && (
                          <p className="text-xs text-slate-400 leading-relaxed">
                            {milestone.description}
                          </p>
                        )}
                        {milestone.deadline && (
                          <div className="text-[11px] font-mono text-slate-500 flex items-center space-x-1 pt-1">
                            <Calendar className="w-3 h-3" />
                            <span>Target: {new Date(milestone.deadline).toLocaleDateString()}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            )}
          </div>

          {/* Constraints & Success Criteria */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
            <Card>
              <CardContent className="pt-6 space-y-3">
                <h4 className="text-xs uppercase font-mono tracking-wider text-slate-400">
                  Enforced Constraints ({goal.constraints?.length || 0})
                </h4>
                {(!goal.constraints || goal.constraints.length === 0) ? (
                  <p className="text-xs text-slate-500 italic">No specific constraints attached</p>
                ) : (
                  <div className="space-y-2">
                    {goal.constraints.map((c) => (
                      <div
                        key={c.id}
                        className="text-xs p-2.5 rounded-lg bg-slate-950 border border-slate-800 flex justify-between items-center"
                      >
                        <span className="font-semibold text-slate-300 capitalize">{c.type}:</span>
                        <span className="font-mono text-slate-400">{c.value}</span>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent className="pt-6 space-y-3">
                <h4 className="text-xs uppercase font-mono tracking-wider text-slate-400">
                  Success Criteria ({goal.success_criteria?.length || 0})
                </h4>
                {(!goal.success_criteria || goal.success_criteria.length === 0) ? (
                  <p className="text-xs text-slate-500 italic">No explicit criteria provided</p>
                ) : (
                  <ul className="space-y-2 text-xs text-slate-300">
                    {goal.success_criteria.map((crit, idx) => (
                      <li key={idx} className="flex items-start space-x-2">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0 mt-0.5" />
                        <span>{crit}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: TASKS & EXECUTION                                                  */}
      {/* ========================================================================= */}
      {activeTab === 'tasks' && (
        <div className="space-y-4 animate-in fade-in duration-200">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center space-x-2">
                <ListChecks className="w-5 h-5 text-emerald-400" />
                <span>Decomposed Tasks ({tasks.length})</span>
              </h3>
              <p className="text-xs text-slate-400">
                Actionable units of work. Complete or update tasks to advance plan execution.
              </p>
            </div>

            <div className="flex items-center space-x-2">
              <Button
                variant="outline"
                size="sm"
                isLoading={decomposeMutation.isPending}
                onClick={() => decomposeMutation.mutate()}
                leftIcon={<Sparkles className="w-4 h-4 text-emerald-400" />}
              >
                Re-Decompose
              </Button>
            </div>
          </div>

          {isLoadingTasks ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="p-4 rounded-xl border border-slate-800 bg-slate-900/40 space-y-2">
                  <div className="flex justify-between">
                    <Skeleton className="h-5 w-48" />
                    <Skeleton className="h-5 w-20" />
                  </div>
                  <Skeleton className="h-4 w-full" />
                </div>
              ))}
            </div>
          ) : tasks.length === 0 ? (
            <EmptyState
              icon={ListChecks}
              title="No Tasks Generated Yet"
              description="Run decomposition to break this goal into concrete actionable tasks with estimated effort."
              action={{
                label: decomposeMutation.isPending ? 'Decomposing...' : 'Decompose Goal Now',
                icon: Sparkles,
                onClick: () => decomposeMutation.mutate(),
              }}
            />
          ) : (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/50 divide-y divide-slate-800/80 overflow-hidden shadow-lg">
              {tasks.map((task) => {
                const isCompleted = task.status === 'COMPLETED';

                return (
                  <div
                    key={task.id}
                    className={`p-4 transition-colors flex items-start space-x-4 ${
                      isCompleted ? 'bg-slate-950/40 opacity-75' : 'hover:bg-slate-900/80'
                    }`}
                  >
                    {/* Task Completion Button / Checkbox */}
                    <button
                      type="button"
                      disabled={isCompleted || completeTaskMutation.isPending}
                      onClick={() => completeTaskMutation.mutate(task.id)}
                      className={`mt-1 p-1 rounded-md border transition-all ${
                        isCompleted
                          ? 'bg-emerald-500/20 border-emerald-500/40 text-emerald-400 cursor-default'
                          : 'border-slate-700 hover:border-emerald-500 text-slate-400 hover:text-emerald-400'
                      }`}
                      title={isCompleted ? 'Task completed' : 'Mark task complete'}
                      aria-label={`Mark task ${task.title} complete`}
                    >
                      <CheckCircle2 className="w-5 h-5" />
                    </button>

                    {/* Task Info */}
                    <div className="flex-1 min-w-0 space-y-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <h4
                          className={`text-sm font-semibold ${
                            isCompleted ? 'line-through text-slate-400' : 'text-white'
                          }`}
                        >
                          {task.title}
                        </h4>

                        <div className="flex items-center space-x-1.5 shrink-0">
                          <Badge variant={task.priority}>{task.priority}</Badge>
                          <Badge variant={isCompleted ? 'completed' : task.status === 'IN_PROGRESS' ? 'active' : 'default'}>
                            {task.status}
                          </Badge>
                        </div>
                      </div>

                      {task.description && (
                        <p className="text-xs text-slate-400 leading-relaxed">
                          {task.description}
                        </p>
                      )}

                      <div className="flex flex-wrap items-center gap-4 text-[11px] font-mono text-slate-500 pt-1">
                        <span className="flex items-center space-x-1">
                          <Clock className="w-3 h-3" />
                          <span>{task.estimated_minutes} mins effort</span>
                        </span>
                        {task.due_at && (
                          <span className="flex items-center space-x-1">
                            <Calendar className="w-3 h-3" />
                            <span>Due: {new Date(task.due_at).toLocaleDateString()}</span>
                          </span>
                        )}
                        {task.completed_at && (
                          <span className="text-emerald-400/80">
                            Completed {formatRelativeTime(task.completed_at)}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Edit Task Action */}
                    <button
                      onClick={() => openEditTask(task)}
                      className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
                      title="Edit task parameters"
                      aria-label="Edit task"
                    >
                      <Edit3 className="w-4 h-4" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 3: DEPENDENCIES & DAG                                                 */}
      {/* ========================================================================= */}
      {activeTab === 'dependencies' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center space-x-2">
                <Network className="w-5 h-5 text-emerald-400" />
                <span>Task Dependency Graph (DAG)</span>
              </h3>
              <p className="text-xs text-slate-400">
                Directed acyclic dependency links and critical path analysis
              </p>
            </div>

            {dependencyGraph && (
              <div className="text-xs font-mono text-slate-400 bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800">
                Critical Path Duration: <span className="text-emerald-400 font-bold">{dependencyGraph.critical_path_duration_minutes}m</span>
              </div>
            )}
          </div>

          {isLoadingDependencies ? (
            <div className="space-y-3">
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-28 w-full" />
            </div>
          ) : !dependencyGraph || dependencyGraph.nodes.length === 0 ? (
            <Card className="text-center py-12 border-dashed border-slate-800">
              <CardContent className="space-y-3">
                <Network className="w-8 h-8 text-slate-500 mx-auto" />
                <p className="text-sm font-medium text-slate-300">No dependency graph available</p>
                <p className="text-xs text-slate-400 max-w-sm mx-auto">
                  Run decomposition to produce the verified dependency graph and topological execution order.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-6">
              {/* Critical Path Sequence Banner */}
              {dependencyGraph.critical_path && dependencyGraph.critical_path.length > 0 && (
                <div className="p-4 rounded-xl bg-slate-900 border border-emerald-500/30 space-y-2">
                  <div className="text-xs font-mono font-semibold uppercase tracking-wider text-emerald-400 flex items-center space-x-2">
                    <GitBranch className="w-4 h-4" />
                    <span>Identified Critical Path ({dependencyGraph.critical_path.length} tasks)</span>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    {dependencyGraph.critical_path.map((taskId, index) => {
                      const taskObj = dependencyGraph.nodes.find((n) => n.id === taskId);
                      return (
                        <React.Fragment key={taskId}>
                          <span className="px-2.5 py-1 rounded-lg bg-slate-950 border border-emerald-500/40 text-xs font-mono text-emerald-300">
                            {taskObj ? taskObj.title : taskId.substring(0, 8)}
                          </span>
                          {index < dependencyGraph.critical_path.length - 1 && (
                            <span className="text-slate-500 font-bold">&rarr;</span>
                          )}
                        </React.Fragment>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Dependency Links Table */}
              <div className="space-y-3">
                <h4 className="text-xs uppercase font-mono tracking-wider text-slate-400">
                  Prerequisite Dependency Relationships ({dependencyGraph.edges.length})
                </h4>

                {dependencyGraph.edges.length === 0 ? (
                  <p className="text-xs text-slate-500 italic p-4 rounded-xl bg-slate-900/40 border border-slate-800">
                    All tasks are currently unconstrained or can execute in parallel.
                  </p>
                ) : (
                  <div className="rounded-xl border border-slate-800 bg-slate-900/60 divide-y divide-slate-800">
                    {dependencyGraph.edges.map((edge) => {
                      const targetTask = dependencyGraph.nodes.find((n) => n.id === edge.task_id);
                      const prereqTask = dependencyGraph.nodes.find((n) => n.id === edge.depends_on_task_id);

                      return (
                        <div key={edge.id} className="p-3 text-xs flex items-center justify-between">
                          <div className="flex items-center space-x-2">
                            <span className="font-semibold text-white">
                              {targetTask ? targetTask.title : edge.task_id.substring(0, 8)}
                            </span>
                            <span className="text-slate-500 font-mono">cannot start until</span>
                            <span className="font-semibold text-emerald-400">
                              {prereqTask ? prereqTask.title : edge.depends_on_task_id.substring(0, 8)}
                            </span>
                          </div>
                          <span className="font-mono text-[10px] uppercase bg-slate-800 px-2 py-0.5 rounded text-slate-300">
                            {edge.dependency_type}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 4: TIMELINE & SCHEDULE                                                */}
      {/* ========================================================================= */}
      {activeTab === 'timeline' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center space-x-2">
                <Calendar className="w-5 h-5 text-emerald-400" />
                <span>Deterministic Execution Timeline</span>
              </h3>
              <p className="text-xs text-slate-400">
                Scheduled execution plan allocating tasks across available user capacity
              </p>
            </div>

            <Button
              size="sm"
              variant="outline"
              isLoading={generatePlanMutation.isPending}
              onClick={() => generatePlanMutation.mutate()}
              leftIcon={<Sparkles className="w-4 h-4 text-emerald-400" />}
            >
              Generate New Schedule
            </Button>
          </div>

          {isLoadingPlan ? (
            <div className="space-y-3">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-48 w-full" />
            </div>
          ) : !activePlan ? (
            <EmptyState
              icon={Calendar}
              title="No Active Schedule Generated"
              description="Click generate to build an optimal schedule respecting working hours, dependencies, and deadlines."
              action={{
                label: generatePlanMutation.isPending ? 'Generating Schedule...' : 'Generate Plan Schedule',
                icon: Sparkles,
                onClick: () => generatePlanMutation.mutate(),
              }}
            />
          ) : (
            <div className="space-y-6">
              {/* Schedule Summary Header */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="text-xs font-mono text-slate-400 uppercase">Feasibility</div>
                  <div className={`text-base font-bold ${activePlan.is_feasible ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {activePlan.is_feasible ? 'Feasible (Completes On Time)' : 'Infeasible (Exceeds Deadline)'}
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="text-xs font-mono text-slate-400 uppercase">Total Scheduled Effort</div>
                  <div className="text-base font-bold text-white font-mono">
                    {Math.round(activePlan.total_duration_minutes / 60)} hrs ({activePlan.total_duration_minutes} mins)
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="text-xs font-mono text-slate-400 uppercase">Plan Version</div>
                  <div className="text-base font-bold text-purple-400 font-mono">
                    v{activePlan.version} ({activePlan.status})
                  </div>
                </div>
              </div>

              {/* Scheduled Time Slots */}
              <div className="space-y-3">
                <h4 className="text-xs uppercase font-mono tracking-wider text-slate-400">
                  Allocated Task Windows ({activePlan.items.length})
                </h4>

                <div className="rounded-2xl border border-slate-800 bg-slate-900/60 divide-y divide-slate-800/80 overflow-hidden shadow-lg">
                  {activePlan.items.map((item, idx) => (
                    <div key={item.id || idx} className="p-4 flex items-center justify-between text-xs hover:bg-slate-900/80 transition-colors">
                      <div className="space-y-1">
                        <div className="font-semibold text-white text-sm">
                          {item.task_title || `Task ${item.task_id.substring(0, 8)}`}
                        </div>
                        {item.rationale && (
                          <p className="text-slate-400 text-xs italic">
                            {item.rationale}
                          </p>
                        )}
                      </div>

                      <div className="text-right font-mono text-slate-300 space-y-0.5">
                        <div className="text-emerald-400 font-semibold">
                          {new Date(item.scheduled_start).toLocaleString(undefined, {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </div>
                        <div className="text-slate-500 text-[11px]">
                          to {new Date(item.scheduled_end).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 5: RISK & DIAGNOSIS                                                   */}
      {/* ========================================================================= */}
      {activeTab === 'risk' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold text-white flex items-center space-x-2">
                <ShieldAlert className="w-5 h-5 text-amber-400" />
                <span>Goal Risk &amp; Diagnostic Engine</span>
              </h3>
              <p className="text-xs text-slate-400">
                Multi-dimensional evaluation of momentum, consistency, bottlenecks, and execution risk
              </p>
            </div>

            <Button
              size="sm"
              variant="outline"
              isLoading={isFetchingEvaluation}
              onClick={() => refetchEvaluation()}
              leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
            >
              Re-Evaluate
            </Button>
          </div>

          {isLoadingEvaluation ? (
            <div className="space-y-4">
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-40 w-full" />
            </div>
          ) : !evaluation ? (
            <Card className="text-center py-12 border-dashed border-slate-800">
              <CardContent className="space-y-3">
                <ShieldCheck className="w-8 h-8 text-slate-500 mx-auto" />
                <h4 className="text-sm font-semibold text-white">Diagnostic evaluation available</h4>
                <p className="text-xs text-slate-400 max-w-sm mx-auto">
                  Evaluate whether the current plan is actively progressing toward completion and detect bottlenecks.
                </p>
                <Button
                  size="sm"
                  variant="primary"
                  isLoading={isFetchingEvaluation}
                  onClick={() => refetchEvaluation()}
                >
                  Run Deep Diagnostic
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-6">
              {/* Primary Diagnostic Banner */}
              <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="text-xs font-mono text-slate-400 uppercase">Forward Momentum</div>
                  <div className={`text-lg font-bold ${evaluation.is_moving_forward ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {evaluation.is_moving_forward ? 'Moving Forward' : 'Stalled / Churning'}
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="text-xs font-mono text-slate-400 uppercase">Evaluated Risk</div>
                  <div className="text-lg font-bold text-amber-400 uppercase font-mono">
                    {evaluation.deadline_risk}
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="text-xs font-mono text-slate-400 uppercase">Consistency Score</div>
                  <div className="text-lg font-bold text-teal-400 font-mono">
                    {Math.round(evaluation.consistency_score * 100)}%
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-1">
                  <div className="text-xs font-mono text-slate-400 uppercase">Remaining Workload</div>
                  <div className="text-lg font-bold text-white font-mono">
                    {Math.round(evaluation.remaining_workload_minutes / 60)}h ({evaluation.remaining_workload_minutes}m)
                  </div>
                </div>
              </div>

              {/* Detected Bottlenecks & Weaknesses */}
              <div className="space-y-3">
                <h4 className="text-xs uppercase font-mono tracking-wider text-slate-400">
                  Detected Execution Weaknesses ({evaluation.weaknesses?.length || 0})
                </h4>

                {(!evaluation.weaknesses || evaluation.weaknesses.length === 0) ? (
                  <p className="text-xs text-emerald-400/90 p-4 rounded-xl bg-emerald-950/20 border border-emerald-800/40">
                    &bull; No execution bottlenecks or critical churn patterns detected for this goal.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {evaluation.weaknesses.map((w, idx) => (
                      <div
                        key={idx}
                        className="p-4 rounded-xl bg-slate-900 border border-amber-500/30 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono font-semibold text-amber-400 uppercase">
                            {w.type}
                          </span>
                          <Badge variant="warning">{w.severity}</Badge>
                        </div>
                        <p className="text-xs text-slate-200">
                          {w.description}
                        </p>
                        {w.recommendation && (
                          <p className="text-xs text-slate-400 italic">
                            Recommendation: {w.recommendation}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 6: PLAN REVISIONS & HISTORY                                           */}
      {/* ========================================================================= */}
      {activeTab === 'versions' && (
        <div className="space-y-6 animate-in fade-in duration-200">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center space-x-2">
              <History className="w-5 h-5 text-purple-400" />
              <span>Historical Plan Versions ({planVersions.length})</span>
            </h3>
            <p className="text-xs text-slate-400">
              Audit log of previous schedules generated for this objective
            </p>
          </div>

          {isLoadingVersions ? (
            <Skeleton className="h-40 w-full" />
          ) : planVersions.length === 0 ? (
            <Card className="text-center py-12 border-dashed border-slate-800">
              <CardContent className="space-y-3">
                <History className="w-8 h-8 text-slate-500 mx-auto" />
                <p className="text-sm font-medium text-slate-300">No historical plans found</p>
                <p className="text-xs text-slate-400 max-w-sm mx-auto">
                  When new schedules are generated or autonomous replanning occurs, versioned revisions are archived here.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="rounded-2xl border border-slate-800 bg-slate-900/60 divide-y divide-slate-800 overflow-hidden shadow-lg">
              {planVersions.map((v) => (
                <div
                  key={v.id}
                  className="p-4 flex items-center justify-between hover:bg-slate-900/90 transition-colors"
                >
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      <span className="font-mono font-bold text-white text-sm">
                        Version {v.version}
                      </span>
                      <Badge variant={v.status === 'ACTIVE' ? 'active' : 'default'}>
                        {v.status}
                      </Badge>
                      <Badge variant={v.is_feasible ? 'success' : 'danger'}>
                        {v.is_feasible ? 'FEASIBLE' : 'INFEASIBLE'}
                      </Badge>
                    </div>

                    <div className="text-xs text-slate-400">
                      {v.reason || 'Routine schedule generation'}
                    </div>

                    <div className="text-[11px] font-mono text-slate-500">
                      Generated: {new Date(v.generated_at).toLocaleString()} &bull; {v.task_count} tasks ({v.total_duration_minutes}m)
                    </div>
                  </div>

                  <div className="flex items-center space-x-2">
                    {v.version > 1 && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setActiveTab('replanning');
                        }}
                      >
                        View Diff
                      </Button>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSelectedPlanVersion(v.version)}
                    >
                      Inspect Schedule
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 7: REPLANNING DIFF VISUALIZATION                                      */}
      {/* ========================================================================= */}
      {activeTab === 'replanning' && (
        <ReplanningDiffViewer
          goalId={goalId}
          goalTitle={goal.title}
          onNavigateToTask={() => setActiveTab('tasks')}
        />
      )}

      {/* ========================================================================= */}
      {/* UPDATE TASK MODAL                                                         */}
      {/* ========================================================================= */}
      <Modal
        isOpen={Boolean(editingTask)}
        onClose={() => setEditingTask(null)}
        title="Edit Task Specification"
        description="Update execution parameters for this goal task."
        maxWidth="md"
      >
        <form onSubmit={handleUpdateTaskSubmit} className="space-y-4 pt-1">
          {taskError && (
            <Alert variant="error" title="Update Error" onDismiss={() => setTaskError(null)}>
              {taskError}
            </Alert>
          )}

          <Input
            id="editTaskTitle"
            label="Task Title"
            value={taskTitle}
            onChange={(e) => setTaskTitle(e.target.value)}
            required
          />

          <div className="space-y-1.5">
            <label
              htmlFor="editTaskDescription"
              className="block text-xs font-medium uppercase tracking-wider text-slate-300"
            >
              Description &amp; Guidance
            </label>
            <textarea
              id="editTaskDescription"
              rows={3}
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              className="w-full bg-slate-900 border border-slate-800 text-slate-100 placeholder-slate-500 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <label
                htmlFor="editTaskPriority"
                className="block text-xs font-medium uppercase tracking-wider text-slate-300"
              >
                Priority
              </label>
              <select
                id="editTaskPriority"
                value={taskPriority}
                onChange={(e) => setTaskPriority(e.target.value as GoalPriority)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-2.5 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="editTaskStatus"
                className="block text-xs font-medium uppercase tracking-wider text-slate-300"
              >
                Status
              </label>
              <select
                id="editTaskStatus"
                value={taskStatus}
                onChange={(e) => setTaskStatus(e.target.value as TaskStatus)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-2.5 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="PENDING">Pending</option>
                <option value="IN_PROGRESS">In Progress</option>
                <option value="COMPLETED">Completed</option>
                <option value="BLOCKED">Blocked</option>
                <option value="CANCELLED">Cancelled</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label
                htmlFor="editTaskMinutes"
                className="block text-xs font-medium uppercase tracking-wider text-slate-300"
              >
                Minutes
              </label>
              <input
                id="editTaskMinutes"
                type="number"
                min={1}
                value={taskEstMinutes}
                onChange={(e) => setTaskEstMinutes(Number(e.target.value) || 1)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-2.5 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
          </div>

          <div className="flex items-center justify-end space-x-2 pt-3 border-t border-slate-800">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setEditingTask(null)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              isLoading={updateTaskMutation.isPending}
            >
              Save Changes
            </Button>
          </div>
        </form>
      </Modal>

      {/* ========================================================================= */}
      {/* HISTORICAL PLAN VERSION DETAILS MODAL                                     */}
      {/* ========================================================================= */}
      <Modal
        isOpen={selectedPlanVersion !== null}
        onClose={() => setSelectedPlanVersion(null)}
        title={`Plan Revision v${selectedPlanVersion}`}
        description="Detailed schedule allocation recorded for this plan version."
        maxWidth="lg"
      >
        {isLoadingHistoricalPlan ? (
          <Skeleton className="h-48 w-full" />
        ) : !historicalPlanDetail ? (
          <p className="text-xs text-slate-400">Failed to load plan details</p>
        ) : (
          <div className="space-y-4 pt-1">
            <div className="flex items-center justify-between text-xs font-mono p-3 bg-slate-950 rounded-lg border border-slate-800">
              <span>Risk: <strong className="text-amber-400">{historicalPlanDetail.risk_level}</strong></span>
              <span>Total Duration: <strong>{historicalPlanDetail.total_duration_minutes}m</strong></span>
              <span>Feasible: <strong className={historicalPlanDetail.is_feasible ? 'text-emerald-400' : 'text-rose-400'}>
                {historicalPlanDetail.is_feasible ? 'YES' : 'NO'}
              </strong></span>
            </div>

            <div className="max-h-80 overflow-y-auto space-y-2 pr-1">
              {historicalPlanDetail.items.map((item, idx) => (
                <div key={idx} className="p-3 bg-slate-950/70 border border-slate-800 rounded-lg text-xs space-y-1">
                  <div className="font-semibold text-white">
                    {item.task_title || `Task ${item.task_id.substring(0, 8)}`}
                  </div>
                  <div className="text-[11px] font-mono text-slate-400 flex justify-between">
                    <span>Start: {new Date(item.scheduled_start).toLocaleString()}</span>
                    <span>End: {new Date(item.scheduled_end).toLocaleString()}</span>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex justify-end pt-2 border-t border-slate-800">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setSelectedPlanVersion(null)}
              >
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>

      {/* Delete Goal Confirmation Modal */}
      <ConfirmDialog
        isOpen={isDeleteConfirmOpen}
        onClose={() => setIsDeleteConfirmOpen(false)}
        onConfirm={() => deleteGoalMutation.mutate()}
        title="Permanently Delete Goal"
        message={`Are you sure you want to permanently delete "${goal.title}"? This will cascade to all associated tasks, schedules, dependencies, and execution history. This action cannot be undone.`}
        confirmText="Delete Goal"
        variant="danger"
        isLoading={deleteGoalMutation.isPending}
      />
    </div>
  );
};
