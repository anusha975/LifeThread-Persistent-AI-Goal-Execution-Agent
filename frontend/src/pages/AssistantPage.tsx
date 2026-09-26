import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { AgentChatInterface } from '../components/chat/AgentChatInterface';

export const AssistantPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const goalId = searchParams.get('goal_id') || undefined;
  const taskId = searchParams.get('task_id') || undefined;

  return (
    <div className="space-y-6">
      <AgentChatInterface initialGoalId={goalId} initialTaskId={taskId} />
    </div>
  );
};
