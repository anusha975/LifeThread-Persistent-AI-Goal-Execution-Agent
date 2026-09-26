import { describe, it, expect } from 'vitest';
import {
  calculateGoalProgress,
  calculateDeadlineRisk,
  calculateOverallSummary,
} from '../utils/dashboardMetrics';
import { Goal } from '../types/goal';

describe('Frontend Dashboard Metrics Utilities', () => {
  it('calculates 0% progress for goal without milestones and not completed', () => {
    const goal: Goal = {
      id: 'g1',
      user_id: 'u1',
      title: 'Learn TypeScript',
      objective: 'Master TS generics and type system',
      priority: 'high',
      status: 'active',
      success_criteria: ['Pass tests'],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      milestones: [],
    };
    const progress = calculateGoalProgress(goal);
    expect(progress.progressPercent).toBe(0);
    expect(progress.hasMilestones).toBe(false);
  });

  it('calculates accurate milestone completion ratio', () => {
    const goal: Goal = {
      id: 'g2',
      user_id: 'u1',
      title: 'Build API',
      objective: 'Launch REST API',
      priority: 'critical',
      status: 'active',
      success_criteria: ['Endpoints up'],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      milestones: [
        {
          id: 'm1',
          goal_id: 'g2',
          title: 'Design DB',
          order_index: 0,
          status: 'completed',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
        {
          id: 'm2',
          goal_id: 'g2',
          title: 'Endpoints',
          order_index: 1,
          status: 'pending',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    };
    const progress = calculateGoalProgress(goal);
    expect(progress.progressPercent).toBe(50);
    expect(progress.completedMilestones).toBe(1);
    expect(progress.totalMilestones).toBe(2);
    expect(progress.hasMilestones).toBe(true);
  });

  it('evaluates deadline risk accurately for distant and overdue deadlines', () => {
    const now = new Date();
    const future = new Date(now.getTime() + 1000 * 60 * 60 * 24 * 30); // 30 days
    const past = new Date(now.getTime() - 1000 * 60 * 60 * 24); // Overdue

    const lowRisk = calculateDeadlineRisk(future.toISOString(), 0, 'active');
    expect(lowRisk.level).toBe('low');
    expect(lowRisk.isOverdue).toBe(false);

    const overdueRisk = calculateDeadlineRisk(past.toISOString(), 0, 'active');
    expect(overdueRisk.level).toBe('critical');
    expect(overdueRisk.isOverdue).toBe(true);
  });

  it('calculates overall summary across active and completed goals', () => {
    const goals: Goal[] = [
      {
        id: 'g1',
        user_id: 'u1',
        title: 'Goal 1',
        objective: 'Obj 1',
        priority: 'critical',
        status: 'completed',
        success_criteria: ['Done'],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        milestones: [
          {
            id: 'm1',
            goal_id: 'g1',
            title: 'M1',
            order_index: 0,
            status: 'completed',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      },
      {
        id: 'g2',
        user_id: 'u1',
        title: 'Goal 2',
        objective: 'Obj 2',
        priority: 'high',
        status: 'active',
        success_criteria: ['In progress'],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        milestones: [
          {
            id: 'm2',
            goal_id: 'g2',
            title: 'M2',
            order_index: 0,
            status: 'pending',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      },
    ];

    const summary = calculateOverallSummary(goals);
    expect(summary.activeGoalsCount).toBe(1);
    expect(summary.completedGoalsCount).toBe(1);
    expect(summary.totalMilestonesCount).toBe(1);
    expect(summary.completedMilestonesCount).toBe(0);
  });
});
