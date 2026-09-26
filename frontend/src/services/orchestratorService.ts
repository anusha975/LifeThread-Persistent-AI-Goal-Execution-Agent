import { apiClient } from './apiClient';
import {
  AgentSession,
  ChatRequest,
  ChatResponse,
  ConversationContextSummary,
} from '../types/orchestrator';

export const orchestratorService = {
  /**
   * Send a conversational message to the Agent Orchestrator.
   */
  async sendMessage(request: ChatRequest): Promise<ChatResponse> {
    return apiClient.post<ChatResponse>('/agent/chat', request);
  },

  /**
   * Retrieve active conversational context summary (active goal, current task, memories).
   */
  async getContextSummary(sessionId?: string): Promise<ConversationContextSummary> {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return apiClient.get<ConversationContextSummary>(`/agent/chat/context${qs}`);
  },

  /**
   * Retrieve conversation history for a specific session.
   */
  async getSession(sessionId: string): Promise<AgentSession> {
    return apiClient.get<AgentSession>(`/agent/chat/sessions/${encodeURIComponent(sessionId)}`);
  },
};
