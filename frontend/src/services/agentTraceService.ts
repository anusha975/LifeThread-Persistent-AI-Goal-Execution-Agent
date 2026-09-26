import { apiClient } from './apiClient';
import { AgentRun, AgentRunSummary, EventStatus } from '../types/agentTrace';

export interface ListRunsParams {
  goalId?: string;
  status?: EventStatus;
  limit?: number;
}

export const agentTraceService = {
  async listRuns(params?: ListRunsParams): Promise<AgentRunSummary[]> {
    const query = new URLSearchParams();
    if (params?.goalId) query.append('goal_id', params.goalId);
    if (params?.status) query.append('status', params.status);
    if (params?.limit) query.append('limit', params.limit.toString());

    const qs = query.toString();
    const endpoint = qs ? `/agent/runs?${qs}` : '/agent/runs';
    return apiClient.get<AgentRunSummary[]>(endpoint);
  },

  async getRun(runId: string): Promise<AgentRun> {
    return apiClient.get<AgentRun>(`/agent/runs/${runId}`);
  },
};
