import { GoalPriority } from "./goal";

export type ReplanningReasonType =
  | "DEADLINE_CHANGED"
  | "AVAILABLE_TIME_CHANGED"
  | "TASK_FAILED"
  | "TASK_BLOCKED"
  | "NEW_REQUIREMENT"
  | "NEW_WEAKNESS_DISCOVERED"
  | "DEPENDENCY_CHANGED"
  | "PRIORITY_CHANGED";

export interface TaskRescheduleItem {
  task_id: string;
  title: string;
  priority: GoalPriority;
  old_start: string | null;
  new_start: string;
  old_end: string | null;
  new_end: string;
  shift_hours: number;
  rationale: string;
}

export interface PriorityChangeItem {
  task_id: string;
  title: string;
  old_priority: GoalPriority;
  new_priority: GoalPriority;
  rationale: string;
}

export interface AddedTaskItem {
  task_id: string;
  title: string;
  priority: GoalPriority;
  scheduled_start?: string | null;
  scheduled_end?: string | null;
}

export interface RemovedTaskItem {
  task_id: string;
  title: string;
}

export interface PlanDiffData {
  old_plan_version: number | null;
  new_plan_version: number;
  why_changed: string;
  what_changed: string;
  tasks_added: AddedTaskItem[];
  tasks_removed: RemovedTaskItem[];
  tasks_rescheduled: TaskRescheduleItem[];
  priority_changes: PriorityChangeItem[];
  tasks_unaffected: Array<{ task_id: string; title: string }>;
  critical_path_changed: boolean;
  old_critical_path_task_ids?: string[];
  new_critical_path_task_ids?: string[];
  old_risk_level: string;
  new_risk_level: string;
  old_completion_date: string | null;
  new_completion_date: string | null;
  why_feasible: string;
}

export interface PlanComparisonItem {
  task_id: string;
  title: string;
  scheduled_start: string;
  scheduled_end: string;
  priority: string;
  rationale: string;
}

export interface PlanComparisonSummary {
  version: number;
  task_count: number;
  total_duration_minutes: number;
  scheduled_start: string | null;
  scheduled_end: string | null;
  risk_level: string;
  is_feasible: boolean;
  status: string;
  items: PlanComparisonItem[];
}

export interface ReplanningDiffResponse {
  plan_changed: boolean;
  status_label: string;
  reason: string;
  why_explanation: string;
  why_feasible: string;
  previous_plan: PlanComparisonSummary | null;
  new_plan: PlanComparisonSummary | null;
  changes: PlanDiffData | null;
  priority_changes: PriorityChangeItem[];
  committed_at: string | null;
}
