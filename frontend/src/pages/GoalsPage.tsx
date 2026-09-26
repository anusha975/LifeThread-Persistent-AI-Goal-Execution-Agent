import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Calendar,
  Filter,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Target,
} from 'lucide-react';
import { goalService } from '../services/goalService';
import { GoalCreatePayload, GoalPriority, GoalStatus } from '../types/goal';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Input } from '../components/ui/Input';
import { Skeleton } from '../components/ui/Skeleton';
import { Alert } from '../components/ui/Alert';
import { Modal } from '../components/ui/Modal';
import { EmptyState } from '../components/ui/EmptyState';
import { APIError } from '../types/api';

export const GoalsPage: React.FC = () => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Filters & State
  const [statusFilter, setStatusFilter] = useState<GoalStatus | 'all'>('all');
  const [searchTerm, setSearchTerm] = useState('');
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  // New Goal Form State
  const [title, setTitle] = useState('');
  const [objective, setObjective] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<GoalPriority>('medium');
  const [deadline, setDeadline] = useState('');
  const [naturalPrompt, setNaturalPrompt] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  // Goal Understanding Mutation
  const understandMutation = useMutation({
    mutationFn: (text: string) => goalService.understandGoal({ text }),
    onSuccess: (data) => {
      if (data.title) setTitle(data.title);
      if (data.objective) setObjective(data.objective);
      if (data.priority) setPriority(data.priority);
      if (data.deadline) {
        try {
          const d = new Date(data.deadline);
          setDeadline(d.toISOString().slice(0, 16));
        } catch {
          // ignore date parse issues
        }
      }
      setFormError(null);
    },
    onError: (err: unknown) => {
      if (err instanceof APIError) {
        setFormError(err.message);
      } else {
        setFormError('Goal understanding failed. Please enter parameters manually.');
      }
    },
  });

  // Query Goals
  const {
    data: goalsData,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['goals', statusFilter],
    queryFn: () =>
      goalService.listGoals({
        status: statusFilter === 'all' ? undefined : statusFilter,
        limit: 100,
      }),
  });

  // Create Goal Mutation
  const createMutation = useMutation({
    mutationFn: (payload: GoalCreatePayload) => goalService.createGoal(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['goals'] });
      setIsCreateOpen(false);
      resetForm();
    },
    onError: (err: unknown) => {
      if (err instanceof APIError) {
        setFormError(err.message);
      } else {
        setFormError('Failed to create goal. Please review your inputs.');
      }
    },
  });

  const resetForm = () => {
    setNaturalPrompt('');
    setTitle('');
    setObjective('');
    setDescription('');
    setPriority('medium');
    setDeadline('');
    setFormError(null);
  };

  const handleCreateSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (title.trim().length < 3) {
      setFormError('Title must be at least 3 characters');
      return;
    }
    if (objective.trim().length < 5) {
      setFormError('Objective must be at least 5 characters');
      return;
    }

    setFormError(null);

    const payload: GoalCreatePayload = {
      title: title.trim(),
      objective: objective.trim(),
      description: description.trim() || null,
      priority,
      deadline: deadline ? new Date(deadline).toISOString() : null,
      success_criteria: [],
    };

    createMutation.mutate(payload);
  };

  // Filtered Goals
  const filteredGoals = (goalsData?.items || []).filter((g) => {
    const term = searchTerm.toLowerCase();
    return g.title.toLowerCase().includes(term) || g.objective.toLowerCase().includes(term);
  });

  const statusTabs: Array<{ id: GoalStatus | 'all'; label: string }> = [
    { id: 'all', label: 'All Goals' },
    { id: 'active', label: 'Active' },
    { id: 'paused', label: 'Paused' },
    { id: 'completed', label: 'Completed' },
    { id: 'failed', label: 'Failed' },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white flex items-center space-x-2">
            <Target className="w-7 h-7 text-emerald-400" />
            <span>Goals Workspace</span>
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Manage, filter, and track autonomous agent goals
          </p>
        </div>

        <Button
          onClick={() => {
            resetForm();
            setIsCreateOpen(true);
          }}
          leftIcon={<Plus className="w-4 h-4" />}
        >
          New Goal
        </Button>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4 bg-slate-900/60 p-3 rounded-xl border border-slate-800">
        {/* Status Tabs */}
        <div className="flex items-center space-x-1 overflow-x-auto pb-2 md:pb-0 scrollbar-none">
          {statusTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap transition-colors ${
                statusFilter === tab.id
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search Input */}
        <div className="w-full md:w-72">
          <Input
            id="search"
            placeholder="Search goals..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            leftIcon={<Search className="w-4 h-4 text-slate-400" />}
            className="py-1.5 text-xs bg-slate-950"
          />
        </div>
      </div>

      {/* Error state */}
      {isError && (
        <div className="p-5 rounded-2xl bg-rose-500/10 border border-rose-500/20 text-center space-y-3 animate-fade-in">
          <div className="w-10 h-10 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center mx-auto">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Failed to load goals</h3>
            <p className="text-xs text-rose-300/80 max-w-md mx-auto mt-1">
              {error instanceof Error ? error.message : 'Error fetching goals from the server.'}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            leftIcon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            Retry Connection
          </Button>
        </div>
      )}

      {/* Goals Content */}
      {isLoading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div
              key={i}
              className="p-5 rounded-xl border border-slate-800 bg-slate-900/40 space-y-3"
            >
              <div className="flex justify-between">
                <Skeleton className="h-5 w-32" />
                <Skeleton className="h-5 w-16" />
              </div>
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </div>
          ))}
        </div>
      ) : filteredGoals.length === 0 ? (
        (goalsData?.items || []).length === 0 ? (
          <EmptyState
            icon={Target}
            title="No Autonomous Goals Created Yet"
            description="Orchestrate long-horizon AI execution by defining your first goal or using natural language interpretation."
            action={{
              label: 'Create Your First Goal',
              icon: Plus,
              onClick: () => {
                resetForm();
                setIsCreateOpen(true);
              },
            }}
          />
        ) : (
          <EmptyState
            icon={Filter}
            title="No Matching Goals Found"
            description={
              searchTerm
                ? `No goals matched your search query "${searchTerm}".`
                : `No goals found with active status filter "${statusFilter}".`
            }
            action={{
              label: 'Clear Filters',
              onClick: () => {
                setSearchTerm('');
                setStatusFilter('all');
              },
            }}
            secondaryAction={{
              label: 'Create New Goal',
              onClick: () => {
                resetForm();
                setIsCreateOpen(true);
              },
            }}
          />
        )
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredGoals.map((goal) => (
            <Card
              key={goal.id}
              hoverEffect
              className="cursor-pointer group flex flex-col justify-between"
              onClick={() => navigate(`/goals/${goal.id}`)}
            >
              <CardHeader className="pb-3">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <Badge variant={goal.priority}>{goal.priority}</Badge>
                  <Badge variant={goal.status}>{goal.status}</Badge>
                </div>
                <CardTitle className="text-base group-hover:text-emerald-400 transition-colors line-clamp-2">
                  {goal.title}
                </CardTitle>
                <CardDescription className="line-clamp-3 text-xs mt-1 leading-relaxed">
                  {goal.objective}
                </CardDescription>
              </CardHeader>

              <CardContent className="pt-2 text-xs text-slate-500 border-t border-slate-800/40 flex items-center justify-between">
                <div className="flex items-center space-x-1.5">
                  <Calendar className="w-3.5 h-3.5 text-slate-400" />
                  <span>
                    {goal.deadline
                      ? new Date(goal.deadline).toLocaleDateString()
                      : 'No deadline'}
                  </span>
                </div>
                <span className="text-emerald-400/80 group-hover:text-emerald-300 font-mono text-[11px]">
                  View details &rarr;
                </span>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* New Goal Creation Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => setIsCreateOpen(false)}
        title="Create Autonomous Goal"
        description="Provide high-level mission parameters. The agent will interpret and structure execution."
        maxWidth="lg"
      >
        <form onSubmit={handleCreateSubmit} className="space-y-4 pt-2">
          {formError && (
            <Alert variant="error" title="Creation Error" onDismiss={() => setFormError(null)}>
              {formError}
            </Alert>
          )}

          {/* AI Goal Understanding Assist */}
          <div className="p-3.5 rounded-xl bg-emerald-950/20 border border-emerald-500/20 space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5" />
                AI Goal Understanding Assist
              </span>
              <span className="text-[10px] text-slate-400">Natural language interpretation</span>
            </div>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="e.g. Build an event-driven payment processor in 45 days with high priority"
                value={naturalPrompt}
                onChange={(e) => setNaturalPrompt(e.target.value)}
                className="flex-1 bg-slate-950 border border-slate-800 text-slate-100 placeholder-slate-500 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-emerald-500"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                isLoading={understandMutation.isPending}
                disabled={naturalPrompt.trim().length < 3}
                onClick={() => understandMutation.mutate(naturalPrompt.trim())}
                className="text-xs shrink-0"
              >
                Understand
              </Button>
            </div>
          </div>

          <Input
            id="goalTitle"
            label="Goal Title"
            placeholder="e.g. Master Rust Programming"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            helperText="At least 3 characters"
          />

          <div className="space-y-1.5">
            <label
              htmlFor="goalObjective"
              className="block text-xs font-medium uppercase tracking-wider text-slate-300"
            >
              Primary Objective
            </label>
            <textarea
              id="goalObjective"
              rows={3}
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              required
              placeholder="e.g. Learn core syntax, build 3 production microservices, and deploy to Kubernetes"
              className="w-full bg-slate-900 border border-slate-800 text-slate-100 placeholder-slate-500 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
            <p className="text-xs text-slate-500">At least 5 characters</p>
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="goalDescription"
              className="block text-xs font-medium uppercase tracking-wider text-slate-300"
            >
              Additional Description (Optional)
            </label>
            <textarea
              id="goalDescription"
              rows={2}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Background context, specific motivations, or constraints"
              className="w-full bg-slate-900 border border-slate-800 text-slate-100 placeholder-slate-500 rounded-lg p-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label
                htmlFor="goalPriority"
                className="block text-xs font-medium uppercase tracking-wider text-slate-300"
              >
                Priority
              </label>
              <select
                id="goalPriority"
                value={priority}
                onChange={(e) => setPriority(e.target.value as GoalPriority)}
                className="w-full bg-slate-900 border border-slate-800 text-slate-100 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500"
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>

            <Input
              id="goalDeadline"
              type="datetime-local"
              label="Target Deadline (Optional)"
              value={deadline}
              onChange={(e) => setDeadline(e.target.value)}
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
              leftIcon={<Sparkles className="w-4 h-4" />}
            >
              Create Goal
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
};
