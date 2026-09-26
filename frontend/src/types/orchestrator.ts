export type AgentIntent =
  | 'CREATE_GOAL'
  | 'NEXT_ACTION'
  | 'WHAT_CHANGED'
  | 'WHY_PLAN_CHANGED'
  | 'CAPACITY_CONSTRAINT'
  | 'REMEMBER_FACT'
  | 'WHAT_IS_BLOCKING'
  | 'COMPLETE_TASK'
  | 'SWITCH_GOAL'
  | 'CHANGE_DEADLINE'
  | 'UPDATE_PRIORITY'
  | 'CLARIFICATION_ANSWER'
  | 'MILESTONE_QUERY'
  | 'MEMORY_QUERY'
  | 'GENERAL_STATUS'
  | 'UNKNOWN';

export type ChatMessageRole = 'user' | 'assistant' | 'system';

export interface ClarificationOption {
  id: string;
  label: string;
  entity_type: 'goal' | 'task' | 'milestone' | 'memory' | string;
  entity_id: string;
  description?: string | null;
}

export interface ClarificationPrompt {
  clarification_type: string;
  prompt_message: string;
  original_intent: string;
  original_slots: Record<string, any>;
  options: ClarificationOption[];
}

export interface ChatMessage {
  id: string;
  role: ChatMessageRole;
  content: string;
  timestamp: string;
  intent?: AgentIntent;
  card_type?: string;
  card_data?: Record<string, any>;
  run_id?: string;
}

export interface AgentSession {
  session_id: string;
  user_id: string;
  active_goal_id?: string | null;
  active_goal_title?: string | null;
  current_task_id?: string | null;
  current_task_title?: string | null;
  active_milestone_id?: string | null;
  active_milestone_title?: string | null;
  last_referenced_memory_id?: string | null;
  pending_clarification?: ClarificationPrompt | null;
  messages: ChatMessage[];
  context_state: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface ChatRequest {
  message: string;
  session_id?: string | null;
  active_goal_id?: string | null;
  current_task_id?: string | null;
}

export interface ChatResponse {
  session_id: string;
  message: ChatMessage;
  intent: AgentIntent;
  active_goal_id?: string | null;
  active_goal_title?: string | null;
  current_task_id?: string | null;
  current_task_title?: string | null;
  active_milestone_id?: string | null;
  active_milestone_title?: string | null;
  last_referenced_memory_id?: string | null;
  clarification_prompt?: ClarificationPrompt | null;
  run_id?: string | null;
  state_updates: Record<string, any>;
  card_type?: string | null;
  card_data?: Record<string, any> | null;
  suggested_replies: string[];
}

export interface ConversationContextSummary {
  session_id: string;
  user_id: string;
  user_name: string;
  active_goal_id?: string | null;
  active_goal_title?: string | null;
  active_goal_status?: string | null;
  current_task_id?: string | null;
  current_task_title?: string | null;
  current_task_priority?: string | null;
  active_milestone_id?: string | null;
  active_milestone_title?: string | null;
  last_referenced_memory_id?: string | null;
  pending_clarification?: ClarificationPrompt | null;
  active_goals_count: number;
  total_memories_count: number;
  learned_weaknesses_count: number;
  preferences_count: number;
  recent_intents: string[];
}

