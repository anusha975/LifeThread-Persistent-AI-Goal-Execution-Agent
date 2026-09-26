import { GoalPriority } from './goal';

export type TaskStatus = 'PENDING' | 'IN_PROGRESS' | 'COMPLETED' | 'BLOCKED' | 'CANCELLED';

export interface Task {
  id: string;
  goal_id: string;
  milestone_id?: string | null;
  version: number;
  title: string;
  description?: string | null;
  status: TaskStatus;
  priority: GoalPriority;
  estimated_minutes: number;
  due_at?: string | null;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskListResponse {
  goal_id: string;
  version: number;
  items: Task[];
  total: number;
}

export interface TaskUpdatePayload {
  title?: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: GoalPriority;
  estimated_minutes?: number;
  due_at?: string | null;
}

export interface TaskDependency {
  id: string;
  task_id: string;
  depends_on_task_id: string;
  dependency_type: string;
  created_at: string;
  updated_at: string;
}

export interface TaskDependencyGraphResponse {
  goal_id: string;
  version: number;
  nodes: Task[];
  edges: TaskDependency[];
  critical_path: string[];
  topological_order: string[];
  critical_path_duration_minutes: number;
}
