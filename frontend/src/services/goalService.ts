import {
  Goal,
  GoalCreatePayload,
  GoalListResponse,
  GoalPriority,
  GoalStatus,
  GoalUpdatePayload,
} from '../types/goal';
import {
  Task,
  TaskDependencyGraphResponse,
  TaskListResponse,
  TaskUpdatePayload,
} from '../types/task';
import { Plan, PlanListResponse } from '../types/plan';
import { GoalEvaluation } from '../types/evaluation';
import { ReplanningDiffResponse } from '../types/replanning';
import { apiClient } from './apiClient';

export interface ListGoalsParams {
  status?: GoalStatus;
  limit?: number;
  offset?: number;
}

export const goalService = {
  // Goal CRUD & Lifecycle
  async listGoals(params?: ListGoalsParams): Promise<GoalListResponse> {
    const query = new URLSearchParams();
    if (params?.status) query.append('status', params.status);
    if (params?.limit) query.append('limit', params.limit.toString());
    if (params?.offset !== undefined) query.append('offset', params.offset.toString());

    const queryString = query.toString();
    const endpoint = queryString ? `/goals?${queryString}` : '/goals';
    return apiClient.get<GoalListResponse>(endpoint);
  },

  async getGoal(id: string): Promise<Goal> {
    return apiClient.get<Goal>(`/goals/${id}`);
  },

  async understandGoal(payload: {
    text: string;
    timezone?: string;
    reference_time?: string;
  }): Promise<{
    title: string;
    objective: string;
    description?: string;
    priority: GoalPriority;
    deadline?: string | null;
    success_criteria?: string[];
  }> {
    return apiClient.post('/goals/understand', payload);
  },

  async createGoal(payload: GoalCreatePayload): Promise<Goal> {
    return apiClient.post<Goal>('/goals', payload);
  },

  async updateGoal(id: string, payload: GoalUpdatePayload): Promise<Goal> {
    return apiClient.patch<Goal>(`/goals/${id}`, payload);
  },

  async deleteGoal(id: string): Promise<void> {
    return apiClient.delete<void>(`/goals/${id}`);
  },

  async pauseGoal(id: string): Promise<Goal> {
    return apiClient.post<Goal>(`/goals/${id}/pause`);
  },

  async resumeGoal(id: string): Promise<Goal> {
    return apiClient.post<Goal>(`/goals/${id}/resume`);
  },

  async completeGoal(id: string): Promise<Goal> {
    return apiClient.post<Goal>(`/goals/${id}/complete`);
  },

  // Tasks Management
  async getTasks(goalId: string, params?: { version?: number; status?: string }): Promise<TaskListResponse> {
    const query = new URLSearchParams();
    if (params?.version) query.append('version', params.version.toString());
    if (params?.status) query.append('status', params.status);
    const qs = query.toString();
    return apiClient.get<TaskListResponse>(qs ? `/goals/${goalId}/tasks?${qs}` : `/goals/${goalId}/tasks`);
  },

  async updateTask(goalId: string, taskId: string, payload: TaskUpdatePayload): Promise<Task> {
    return apiClient.patch<Task>(`/goals/${goalId}/tasks/${taskId}`, payload);
  },

  async completeTask(goalId: string, taskId: string): Promise<Task> {
    return apiClient.post<Task>(`/goals/${goalId}/tasks/${taskId}/complete`);
  },

  // Dependencies Graph
  async getDependencies(goalId: string, version?: number): Promise<TaskDependencyGraphResponse> {
    const qs = version ? `?version=${version}` : '';
    return apiClient.get<TaskDependencyGraphResponse>(`/goals/${goalId}/dependencies${qs}`);
  },

  // Plans & Timeline
  async getActivePlan(goalId: string): Promise<Plan> {
    return apiClient.get<Plan>(`/goals/${goalId}/plan`);
  },

  async getPlans(goalId: string): Promise<PlanListResponse> {
    return apiClient.get<PlanListResponse>(`/goals/${goalId}/plans`);
  },

  async getPlanByVersion(goalId: string, version: number): Promise<Plan> {
    return apiClient.get<Plan>(`/goals/${goalId}/plans/${version}`);
  },

  async generatePlan(goalId: string): Promise<Plan> {
    return apiClient.post<Plan>(`/goals/${goalId}/plan`);
  },

  // Evaluation & Risk Engine
  async evaluateGoal(goalId: string): Promise<GoalEvaluation> {
    return apiClient.post<GoalEvaluation>(`/goals/${goalId}/evaluate`);
  },

  // Decomposition trigger
  async decomposeGoal(goalId: string): Promise<unknown> {
    return apiClient.post(`/goals/${goalId}/decompose`);
  },

  // Replanning & Plan Diff Engine
  async getReplanningDiff(
    goalId: string,
    versionA?: number,
    versionB?: number
  ): Promise<ReplanningDiffResponse> {
    const query = new URLSearchParams();
    if (versionA !== undefined) query.append('version_a', versionA.toString());
    if (versionB !== undefined) query.append('version_b', versionB.toString());
    const qs = query.toString();
    return apiClient.get<ReplanningDiffResponse>(
      qs ? `/goals/${goalId}/replanning-diff?${qs}` : `/goals/${goalId}/replanning-diff`
    );
  },

  async triggerReplan(
    goalId: string,
    payload: { reason: string; description: string; details?: Record<string, unknown> }
  ): Promise<unknown> {
    return apiClient.post(`/goals/${goalId}/replan`, payload);
  },
};
