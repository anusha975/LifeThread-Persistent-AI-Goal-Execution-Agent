export interface LearningMemory {
  id: string;
  content: string;
  memory_type: string;
  confidence: number;
  importance_score: number;
  status: string;
  access_count: number;
  created_at: string;
  metadata?: {
    goal_id?: string;
    task_id?: string;
    domain?: string;
    topic?: string;
    [key: string]: unknown;
  };
}

export interface PermissionApproval {
  id: string;
  user: string;
  action: string;
  reason: string;
  timestamp: string;
  decision: string;
  request_id?: string | null;
  is_explicit: boolean;
  metadata?: Record<string, unknown>;
}

export interface PendingPermissionRequest {
  id: string;
  user: string;
  action: string;
  reason: string;
  parameters: Record<string, unknown>;
  context: Record<string, unknown>;
  created_at: string;
  expires_at: string;
  status: string;
  risk_level: string;
}

export type ActivityItemType =
  "learning_memory" | "approval" | "pending_request" | "goal_event";

export interface DashboardActivityItem {
  id: string;
  type: ActivityItemType;
  title: string;
  description: string;
  timestamp: string;
  badge?: string;
  badgeVariant?: "default" | "success" | "warning" | "danger" | "info";
  metadata?: Record<string, unknown>;
}
