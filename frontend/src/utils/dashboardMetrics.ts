import { Goal, GoalMilestone, GoalPriority } from '../types/goal';

export interface GoalProgressInfo {
  progressPercent: number;
  completedMilestones: number;
  totalMilestones: number;
  hasMilestones: boolean;
}

export interface NextActionInfo {
  title: string;
  status: 'in_progress' | 'pending' | 'none';
  milestone?: GoalMilestone;
  isDefined: boolean;
}

export type DeadlineRiskLevel = 'critical' | 'high' | 'medium' | 'low' | 'none';

export interface DeadlineRiskInfo {
  level: DeadlineRiskLevel;
  label: string;
  text: string;
  daysRemaining: number | null;
  hoursRemaining: number | null;
  isOverdue: boolean;
}

export interface DashboardOverallSummary {
  overallProgressPercent: number;
  totalMilestonesCount: number;
  completedMilestonesCount: number;
  activeGoalsCount: number;
  completedGoalsCount: number;
  highestPriority: GoalPriority | null;
  nearestDeadline: {
    goal: Goal;
    risk: DeadlineRiskInfo;
  } | null;
  urgentNextAction: {
    goal: Goal;
    action: NextActionInfo;
  } | null;
}

/**
 * Calculates progress for an individual goal based on its actual milestones.
 */
export function calculateGoalProgress(goal: Goal): GoalProgressInfo {
  const milestones = goal.milestones || [];
  const total = milestones.length;

  if (total === 0) {
    const isCompleted = goal.status === 'completed';
    return {
      progressPercent: isCompleted ? 100 : 0,
      completedMilestones: isCompleted ? 1 : 0,
      totalMilestones: 0,
      hasMilestones: false,
    };
  }

  const completed = milestones.filter((m) => m.status === 'completed').length;
  const progressPercent = Math.round((completed / total) * 100);

  return {
    progressPercent,
    completedMilestones: completed,
    totalMilestones: total,
    hasMilestones: true,
  };
}

/**
 * Determines the immediate next actionable milestone for a goal.
 */
export function getGoalNextAction(goal: Goal): NextActionInfo {
  const milestones = goal.milestones ? [...goal.milestones] : [];

  if (milestones.length === 0) {
    return {
      title: 'No pending milestones configured',
      status: 'none',
      isDefined: false,
    };
  }

  // Sort by order_index
  milestones.sort((a, b) => a.order_index - b.order_index);

  // First priority: currently in_progress milestone
  const inProgress = milestones.find((m) => m.status === 'in_progress');
  if (inProgress) {
    return {
      title: inProgress.title,
      status: 'in_progress',
      milestone: inProgress,
      isDefined: true,
    };
  }

  // Second priority: first pending milestone
  const pending = milestones.find((m) => m.status === 'pending');
  if (pending) {
    return {
      title: pending.title,
      status: 'pending',
      milestone: pending,
      isDefined: true,
    };
  }

  // If all milestones completed
  return {
    title: 'All milestones completed',
    status: 'none',
    isDefined: true,
  };
}

/**
 * Computes deadline risk based on real timestamp vs current time and progress.
 */
export function calculateDeadlineRisk(
  deadlinestr: string | null | undefined,
  progressPercent: number,
  goalStatus: string
): DeadlineRiskInfo {
  if (!deadlinestr) {
    return {
      level: 'none',
      label: 'Unconstrained',
      text: 'No deadline set',
      daysRemaining: null,
      hoursRemaining: null,
      isOverdue: false,
    };
  }

  if (goalStatus === 'completed') {
    return {
      level: 'low',
      label: 'Completed',
      text: 'Goal completed',
      daysRemaining: null,
      hoursRemaining: null,
      isOverdue: false,
    };
  }

  const deadlineDate = new Date(deadlinestr).getTime();
  const now = Date.now();
  const diffMs = deadlineDate - now;
  const hoursRemaining = Math.round(diffMs / (1000 * 60 * 60));
  const daysRemaining = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  if (diffMs <= 0) {
    const overdueDays = Math.abs(daysRemaining) || 1;
    return {
      level: 'critical',
      label: 'Overdue',
      text: `Overdue by ${overdueDays} day${overdueDays > 1 ? 's' : ''}`,
      daysRemaining,
      hoursRemaining,
      isOverdue: true,
    };
  }

  if (hoursRemaining <= 48 && progressPercent < 100) {
    return {
      level: 'high',
      label: 'High Risk',
      text: `Due in ${hoursRemaining} hour${hoursRemaining > 1 ? 's' : ''}`,
      daysRemaining,
      hoursRemaining,
      isOverdue: false,
    };
  }

  if (daysRemaining <= 7 && progressPercent < 50) {
    return {
      level: 'medium',
      label: 'Moderate Risk',
      text: `Due in ${daysRemaining} day${daysRemaining > 1 ? 's' : ''} (${progressPercent}% complete)`,
      daysRemaining,
      hoursRemaining,
      isOverdue: false,
    };
  }

  return {
    level: 'low',
    label: 'On Track',
    text: daysRemaining > 1 ? `Due in ${daysRemaining} days` : 'Due today',
    daysRemaining,
    hoursRemaining,
    isOverdue: false,
  };
}

const priorityRank: Record<GoalPriority, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
};

/**
 * Computes overall dashboard summary across all goals strictly from backend records.
 */
export function calculateOverallSummary(goals: Goal[]): DashboardOverallSummary {
  const activeGoals = goals.filter((g) => g.status === 'active');
  const completedGoals = goals.filter((g) => g.status === 'completed');

  let totalMilestonesCount = 0;
  let completedMilestonesCount = 0;

  activeGoals.forEach((g) => {
    const progress = calculateGoalProgress(g);
    totalMilestonesCount += progress.totalMilestones;
    completedMilestonesCount += progress.completedMilestones;
  });

  // Calculate real overall percentage
  let overallProgressPercent = 0;
  if (totalMilestonesCount > 0) {
    overallProgressPercent = Math.round((completedMilestonesCount / totalMilestonesCount) * 100);
  } else if (goals.length > 0) {
    overallProgressPercent = Math.round((completedGoals.length / goals.length) * 100);
  }

  // Find highest active priority
  let highestPriority: GoalPriority | null = null;
  activeGoals.forEach((g) => {
    if (!highestPriority || priorityRank[g.priority] > priorityRank[highestPriority]) {
      highestPriority = g.priority;
    }
  });

  // Find nearest active deadline
  let nearestDeadlineGoal: { goal: Goal; risk: DeadlineRiskInfo } | null = null;
  activeGoals.forEach((g) => {
    if (g.deadline) {
      const progress = calculateGoalProgress(g);
      const risk = calculateDeadlineRisk(g.deadline, progress.progressPercent, g.status);
      if (!nearestDeadlineGoal) {
        nearestDeadlineGoal = { goal: g, risk };
      } else {
        const currentTarget = new Date(g.deadline).getTime();
        const existingTarget = new Date(nearestDeadlineGoal.goal.deadline!).getTime();
        if (currentTarget < existingTarget) {
          nearestDeadlineGoal = { goal: g, risk };
        }
      }
    }
  });

  // Find most urgent next action (from highest priority goal with a pending/in_progress action)
  let urgentNextAction: { goal: Goal; action: NextActionInfo } | null = null;
  const sortedActive = [...activeGoals].sort(
    (a, b) => priorityRank[b.priority] - priorityRank[a.priority]
  );

  for (const g of sortedActive) {
    const action = getGoalNextAction(g);
    if (action.isDefined && action.status !== 'none') {
      urgentNextAction = { goal: g, action };
      break;
    }
  }

  return {
    overallProgressPercent,
    totalMilestonesCount,
    completedMilestonesCount,
    activeGoalsCount: activeGoals.length,
    completedGoalsCount: completedGoals.length,
    highestPriority,
    nearestDeadline: nearestDeadlineGoal,
    urgentNextAction,
  };
}

/**
 * Human readable relative time format.
 */
export function formatRelativeTime(dateString: string): string {
  try {
    const timestamp = new Date(dateString).getTime();
    if (isNaN(timestamp)) return dateString;

    const diffSeconds = Math.round((Date.now() - timestamp) / 1000);

    if (diffSeconds < 60) return 'Just now';
    if (diffSeconds < 3600) return `${Math.floor(diffSeconds / 60)}m ago`;
    if (diffSeconds < 86400) return `${Math.floor(diffSeconds / 3600)}h ago`;
    if (diffSeconds < 604800) return `${Math.floor(diffSeconds / 86400)}d ago`;

    return new Date(dateString).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateString;
  }
}
