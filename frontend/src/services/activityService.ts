import { apiClient } from './apiClient';
import {
  DashboardActivityItem,
  LearningMemory,
  PendingPermissionRequest,
  PermissionApproval,
} from '../types/activity';

export const activityService = {
  async getLearningMemories(): Promise<LearningMemory[]> {
    try {
      return await apiClient.get<LearningMemory[]>('/learning/memories');
    } catch {
      return [];
    }
  },

  async getApprovals(): Promise<PermissionApproval[]> {
    try {
      return await apiClient.get<PermissionApproval[]>('/permissions/approvals');
    } catch {
      return [];
    }
  },

  async getPendingRequests(): Promise<PendingPermissionRequest[]> {
    try {
      return await apiClient.get<PendingPermissionRequest[]>('/permissions/requests/pending');
    } catch {
      return [];
    }
  },

  async approvePermissionRequest(requestId: string, reason = 'Approved via Dashboard'): Promise<void> {
    await apiClient.post(`/permissions/requests/${requestId}/approve`, { reason });
  },

  async rejectPermissionRequest(requestId: string, reason = 'Rejected via Dashboard'): Promise<void> {
    await apiClient.post(`/permissions/requests/${requestId}/reject`, { reason });
  },

  async getCombinedActivityFeed(): Promise<DashboardActivityItem[]> {
    const [memories, approvals] = await Promise.all([
      this.getLearningMemories(),
      this.getApprovals(),
    ]);

    const feed: DashboardActivityItem[] = [];

    // Map learning memories
    for (const mem of memories) {
      feed.push({
        id: `mem-${mem.id}`,
        type: 'learning_memory',
        title: `Agent Insight: ${mem.metadata?.topic || mem.metadata?.domain || 'Autonomous Learning'}`,
        description: mem.content,
        timestamp: mem.created_at,
        badge: `${Math.round(mem.confidence * 100)}% Confidence`,
        badgeVariant: mem.confidence >= 0.8 ? 'success' : 'info',
        metadata: mem.metadata,
      });
    }

    // Map approval audit records
    for (const app of approvals) {
      feed.push({
        id: `app-${app.id}`,
        type: 'approval',
        title: `Action ${app.decision}: ${app.action}`,
        description: app.reason || `Authorized by ${app.user}`,
        timestamp: app.timestamp,
        badge: app.decision,
        badgeVariant: app.decision === 'APPROVED' ? 'success' : 'default',
        metadata: app.metadata,
      });
    }

    // Sort descending by timestamp
    feed.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

    return feed;
  },
};
