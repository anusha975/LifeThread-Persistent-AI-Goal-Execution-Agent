export type MemoryCategory =
  | 'Goal memory'
  | 'Preference'
  | 'Past outcome'
  | 'Learned weakness'
  | 'Relevant knowledge';

export interface RelatedGoalInfo {
  id: string;
  title: string;
}

export interface MemorySourceDetail {
  source_name: string;
  provenance: string;
  task_id?: string | null;
  task_title?: string | null;
  domain?: string | null;
  topic?: string | null;
  outcome_id?: string | null;
  epistemic_qualifier?: string | null;
  is_factual?: boolean | null;
  is_hypothesis?: boolean | null;
  user_corrected: boolean;
  corrected_at?: string | null;
  original_content?: string | null;
  raw_metadata: Record<string, unknown>;
}

export interface UserMemoryItem {
  id: string;
  memory: string;
  source: string;
  source_details: MemorySourceDetail;
  confidence: number;
  importance_score: number;
  category: MemoryCategory;
  memory_type: string;
  related_goal?: RelatedGoalInfo | null;
  status: string;
  access_count: number;
  created_at: string;
  updated_at: string;
}

export interface MemoryCorrectionPayload {
  content: string;
  confidence?: number;
  category?: MemoryCategory;
}

export interface MemoryCreatePayload {
  content: string;
  category: MemoryCategory;
  confidence?: number;
  goal_id?: string;
}

export interface MemoryListResponse {
  items: UserMemoryItem[];
  total: number;
  category_counts: Record<string, number>;
}
