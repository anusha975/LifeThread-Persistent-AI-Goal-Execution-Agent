export interface Weakness {
  type: string;
  severity: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  description: string;
  impact_score: number;
  recommendation?: string;
  affected_task_ids?: string[];
}

export interface RiskAssessment {
  overall_risk_score: number;
  risk_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  primary_risk_driver?: string;
  mitigation_strategy?: string;
}

export interface GoalEvaluation {
  goal_id: string;
  user_id: string;
  is_moving_forward: boolean;
  completion_ratio: number;
  weighted_progress: number;
  performance_score: number;
  consistency_score: number;
  deadline_risk: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
  remaining_workload_minutes: number;
  total_tasks: number;
  completed_tasks: number;
  in_progress_tasks: number;
  blocked_tasks: number;
  failed_tasks: number;
  pending_tasks: number;
  blocked_dependencies_count: number;
  recent_failures_count: number;
  confidence: number;
  risk_assessment?: RiskAssessment;
  weaknesses?: Weakness[];
  recommended_adjustments?: string[];
}
