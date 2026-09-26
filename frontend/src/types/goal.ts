export type GoalStatus =
  "active" | "paused" | "completed" | "archived" | "failed";
export type GoalPriority = "low" | "medium" | "high" | "critical";
export type MilestoneStatus =
  "pending" | "in_progress" | "completed" | "failed";

export interface GoalConstraint {
  id: string;
  goal_id: string;
  type: string;
  value: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface GoalConstraintCreate {
  type: string;
  value: string;
  metadata?: Record<string, unknown>;
}

export interface GoalMilestone {
  id: string;
  goal_id: string;
  title: string;
  description?: string | null;
  status: MilestoneStatus;
  order_index: number;
  deadline?: string | null;
  created_at: string;
  updated_at: string;
}

export interface GoalMilestoneCreate {
  title: string;
  description?: string | null;
  status?: MilestoneStatus;
  order_index?: number;
  deadline?: string | null;
}

export interface Goal {
  id: string;
  user_id: string;
  title: string;
  objective: string;
  description?: string | null;
  status: GoalStatus;
  priority: GoalPriority;
  deadline?: string | null;
  success_criteria: string[];
  created_at: string;
  updated_at: string;
  constraints?: GoalConstraint[];
  milestones?: GoalMilestone[];
}

export interface GoalCreatePayload {
  title: string;
  objective: string;
  description?: string | null;
  priority?: GoalPriority;
  deadline?: string | null;
  success_criteria?: string[];
  constraints?: GoalConstraintCreate[];
  milestones?: GoalMilestoneCreate[];
}

export interface GoalUpdatePayload {
  title?: string;
  objective?: string;
  description?: string | null;
  priority?: GoalPriority;
  deadline?: string | null;
  success_criteria?: string[];
}

export interface GoalListResponse {
  items: Goal[];
  total: number;
  limit: number;
  offset: number;
}
