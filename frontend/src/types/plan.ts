import { GoalPriority } from "./goal";

export type PlanStatus = "DRAFT" | "ACTIVE" | "SUPERSEDED" | "ARCHIVED";

export interface PlanItem {
  id: string;
  plan_id: string;
  task_id: string;
  task_title?: string | null;
  scheduled_start: string;
  scheduled_end: string;
  priority: GoalPriority;
  rationale?: string | null;
}

export interface Plan {
  id: string;
  goal_id: string;
  version: number;
  status: PlanStatus;
  generated_at: string;
  reason?: string | null;
  is_feasible: boolean;
  deadline_risk: number;
  risk_level: string;
  schedule_utilization: number;
  total_duration_minutes: number;
  scheduled_start?: string | null;
  scheduled_end?: string | null;
  items: PlanItem[];
  metadata?: Record<string, unknown>;
}

export interface PlanSummary {
  id: string;
  goal_id: string;
  version: number;
  status: PlanStatus;
  generated_at: string;
  reason?: string | null;
  is_feasible: boolean;
  risk_level: string;
  total_duration_minutes: number;
  task_count: number;
  scheduled_start?: string | null;
  scheduled_end?: string | null;
}

export interface PlanListResponse {
  goal_id: string;
  items: PlanSummary[];
  total: number;
}
