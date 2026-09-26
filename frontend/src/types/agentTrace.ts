export type ExecutionEventType =
  | 'AGENT_RUN'
  | 'DECISION'
  | 'TOOL_CALL'
  | 'TOOL_RESULT'
  | 'EVALUATION'
  | 'STATE_UPDATE';

export type EventStatus =
  | 'SUCCESS'
  | 'PENDING'
  | 'RUNNING'
  | 'FAILED'
  | 'WARNING'
  | 'SKIPPED';

export interface AgentExecutionEvent {
  id: string;
  run_id: string;
  user_id: string;
  timestamp: string;
  event_type: ExecutionEventType;
  status: EventStatus;
  short_explanation: string;
  goal_id?: string | null;
  goal_title?: string | null;
  task_id?: string | null;
  task_title?: string | null;
  tool_name?: string | null;
  tool_parameters?: Record<string, unknown>;
  tool_result?: Record<string, unknown>;
  state_changes?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface AgentRun {
  id: string;
  user_id: string;
  trigger: string;
  status: EventStatus;
  goal_id?: string | null;
  goal_title?: string | null;
  task_id?: string | null;
  task_title?: string | null;
  summary: string;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  events: AgentExecutionEvent[];
}

export interface AgentRunSummary {
  id: string;
  user_id: string;
  trigger: string;
  status: EventStatus;
  goal_id?: string | null;
  goal_title?: string | null;
  task_id?: string | null;
  task_title?: string | null;
  summary: string;
  started_at: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  event_count: number;
}
