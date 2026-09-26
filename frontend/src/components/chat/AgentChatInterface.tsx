import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Brain,
  CheckCircle2,
  Clock,
  ExternalLink,
  GitBranch,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  Target,
  Trash2,
  User as UserIcon,
} from 'lucide-react';
import { orchestratorService } from '../../services/orchestratorService';
import { ChatMessage, ChatRequest, ChatResponse } from '../../types/orchestrator';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { ConfirmDialog } from '../ui/ConfirmDialog';

interface AgentChatInterfaceProps {
  initialGoalId?: string;
  initialTaskId?: string;
  compactMode?: boolean;
}

export const AgentChatInterface: React.FC<AgentChatInterfaceProps> = ({
  initialGoalId,
  initialTaskId,
  compactMode = false,
}) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const [sessionId, setSessionId] = useState<string>(() => {
    return localStorage.getItem('lifethread_active_chat_session') || '';
  });
  const [inputMessage, setInputMessage] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isClearConfirmOpen, setIsClearConfirmOpen] = useState(false);

  const handleClearChat = () => {
    setMessages([]);
    setSessionId('');
    localStorage.removeItem('lifethread_active_chat_session');
    setIsClearConfirmOpen(false);
  };

  // 1. Fetch Context Summary
  const { data: contextSummary, refetch: refetchContext } = useQuery({
    queryKey: ['chatContext', sessionId],
    queryFn: () => orchestratorService.getContextSummary(sessionId || undefined),
    refetchInterval: 15000,
  });

  // Keep local sessionId synced if context returns a new one
  useEffect(() => {
    if (contextSummary?.session_id && !sessionId) {
      setSessionId(contextSummary.session_id);
      localStorage.setItem('lifethread_active_chat_session', contextSummary.session_id);
    }
  }, [contextSummary, sessionId]);

  // Load existing session history if available
  useEffect(() => {
    if (sessionId && messages.length === 0) {
      orchestratorService
        .getSession(sessionId)
        .then((s) => {
          if (s?.messages && s.messages.length > 0) {
            setMessages(s.messages);
          }
        })
        .catch(() => {
          // If session expired or not found, start fresh
        });
    }
  }, [sessionId, messages.length]);

  // Auto-scroll to bottom of messages
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // 2. Chat Mutation
  const chatMutation = useMutation({
    mutationFn: (req: ChatRequest) => orchestratorService.sendMessage(req),
    onSuccess: (data: ChatResponse) => {
      if (!sessionId) {
        setSessionId(data.session_id);
        localStorage.setItem('lifethread_active_chat_session', data.session_id);
      }
      setMessages((prev) => [...prev, data.message]);
      refetchContext();
      queryClient.invalidateQueries({ queryKey: ['goals'] });
      queryClient.invalidateQueries({ queryKey: ['memories'] });
      queryClient.invalidateQueries({ queryKey: ['agentRuns'] });
    },
  });

  const handleSendMessage = (textToSend?: string) => {
    const text = (textToSend || inputMessage).trim();
    if (!text || chatMutation.isPending) return;

    const userMsg: ChatMessage = {
      id: `client-${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputMessage('');

    chatMutation.mutate({
      message: text,
      session_id: sessionId || null,
      active_goal_id: initialGoalId || contextSummary?.active_goal_id || null,
      current_task_id: initialTaskId || contextSummary?.current_task_id || null,
    });

    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const quickPrompts = [
    'What should I do next?',
    'What changed?',
    'Why did my plan change?',
    'I only have one hour today.',
    'Remember that I struggle with SQL joins.',
    'What is blocking my goal?',
    'Create a goal: Learn Advanced Rust in 30 days',
  ];

  return (
    <div className={`flex flex-col ${compactMode ? 'h-[600px]' : 'h-[calc(100vh-140px)] min-h-[550px]'} rounded-2xl bg-slate-900 border border-slate-800 shadow-2xl overflow-hidden`}>
      {/* ========================================================================= */}
      {/* 1. STATEFUL CONTEXT HEADER BAR                                            */}
      {/* ========================================================================= */}
      <div className="bg-slate-950/80 border-b border-slate-800 px-4 py-3 shrink-0 backdrop-blur-md flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 p-0.5 shadow-md shadow-emerald-500/20">
            <div className="w-full h-full bg-slate-950 rounded-[10px] flex items-center justify-center">
              <Sparkles className="w-4 h-4 text-emerald-400" />
            </div>
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-sm font-bold text-white tracking-tight">Agent Orchestrator</h2>
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-[10px] font-mono text-emerald-400 uppercase tracking-widest font-semibold">
                Live State Connected
              </span>
            </div>
            <p className="text-[11px] text-slate-400">
              Natural-language commands with real goal, planning, memory, and evaluation state.
            </p>
          </div>
        </div>

        {/* Real Context Pills */}
        <div className="flex items-center space-x-2 overflow-x-auto text-xs">
          {/* Active Goal Pill */}
          {contextSummary?.active_goal_title ? (
            <button
              onClick={() => contextSummary.active_goal_id && navigate(`/goals/${contextSummary.active_goal_id}`)}
              className="flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-emerald-950/40 border border-emerald-500/30 text-emerald-300 hover:bg-emerald-900/40 transition-colors"
              title="Click to view goal workspace"
            >
              <Target className="w-3.5 h-3.5 text-emerald-400" />
              <span className="max-w-[140px] truncate font-medium">
                Goal: {contextSummary.active_goal_title}
              </span>
              <ExternalLink className="w-3 h-3 opacity-60" />
            </button>
          ) : (
            <span className="px-2.5 py-1 rounded-lg bg-slate-800 text-slate-400 text-xs">
              No Active Goal
            </span>
          )}

          {/* Current Focus Task Pill */}
          {contextSummary?.current_task_title && (
            <div className="hidden sm:flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-sky-950/40 border border-sky-500/30 text-sky-300">
              <Clock className="w-3.5 h-3.5 text-sky-400" />
              <span className="max-w-[140px] truncate">
                Task: {contextSummary.current_task_title}
              </span>
            </div>
          )}

          {/* User Memory Badge */}
          <button
            onClick={() => navigate('/memories')}
            className="flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-purple-950/40 border border-purple-500/30 text-purple-300 hover:bg-purple-900/40 transition-colors"
            title="Inspect remembered context"
          >
            <Brain className="w-3.5 h-3.5 text-purple-400" />
            <span>{contextSummary?.total_memories_count || 0} Memories</span>
          </button>

          {/* Reset / Clear Thread Button */}
          {messages.length > 0 && (
            <button
              onClick={() => setIsClearConfirmOpen(true)}
              className="flex items-center space-x-1 px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-rose-500/10 hover:text-rose-400 text-slate-400 border border-slate-700/60 hover:border-rose-500/30 transition-colors"
              title="Reset conversation session"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">Reset</span>
            </button>
          )}
        </div>
      </div>

      {/* ========================================================================= */}
      {/* 2. CONVERSATION MESSAGE STREAM                                            */}
      {/* ========================================================================= */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-4">
        {/* Welcome Message if thread empty */}
        {messages.length === 0 && (
          <div className="text-center py-8 space-y-4 max-w-xl mx-auto">
            <div className="w-12 h-12 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mx-auto text-emerald-400">
              <Bot className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <h3 className="text-base font-bold text-white">How can LifeThread assist you today?</h3>
              <p className="text-xs text-slate-400 leading-relaxed">
                I am not a generic chatbot. I directly orchestrate your real LifeThread state.
                Tell me what to execute, ask for your next action, or adjust your daily capacity.
              </p>
            </div>

            {/* Quick Prompts Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left pt-2">
              {quickPrompts.map((prompt, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSendMessage(prompt)}
                  className="p-2.5 rounded-xl bg-slate-800/60 hover:bg-slate-800 border border-slate-700/60 hover:border-emerald-500/40 text-xs text-slate-200 transition-all flex items-center justify-between group"
                >
                  <span className="truncate mr-2 font-mono text-[11px]">{prompt}</span>
                  <ArrowRight className="w-3.5 h-3.5 text-slate-500 group-hover:text-emerald-400 shrink-0 transition-transform group-hover:translate-x-0.5" />
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Messages Stream */}
        {messages.map((msg, index) => (
          <div
            key={msg.id || index}
            className={`flex flex-col ${msg.role === 'user' ? 'items-end' : 'items-start'} space-y-1.5`}
          >
            {/* Sender Tag */}
            <div className="flex items-center space-x-1.5 text-[10px] font-mono text-slate-400 px-1">
              {msg.role === 'user' ? (
                <>
                  <span>You</span>
                  <UserIcon className="w-3 h-3 text-emerald-400" />
                </>
              ) : (
                <>
                  <Bot className="w-3 h-3 text-emerald-400" />
                  <span className="font-semibold text-emerald-400">LifeThread Agent</span>
                  {msg.intent && (
                    <span className="bg-slate-800 text-slate-400 px-1.5 py-0.2 rounded border border-slate-700">
                      {msg.intent}
                    </span>
                  )}
                </>
              )}
            </div>

            {/* Message Bubble */}
            <div
              className={`max-w-[85%] sm:max-w-[75%] rounded-2xl p-4 text-xs sm:text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-emerald-600 text-white rounded-tr-none shadow-lg shadow-emerald-950/20'
                  : 'bg-slate-950/90 text-slate-100 rounded-tl-none border border-slate-800 shadow-md space-y-3'
              }`}
            >
              <div className="whitespace-pre-wrap">{msg.content}</div>

              {/* Embedded Rich Card Renderers */}
              {msg.card_type && msg.card_data && (
                <div className="pt-2 border-t border-slate-800/80 mt-2">
                  {/* Card 1: Goal Created */}
                  {msg.card_type === 'goal_created' && (
                    <div className="p-3 rounded-xl bg-emerald-950/30 border border-emerald-500/30 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-emerald-300 uppercase">
                          Goal Created &amp; Scheduled
                        </span>
                        <Badge variant="success">Plan v1</Badge>
                      </div>
                      <div className="font-semibold text-white text-sm">
                        {msg.card_data.title}
                      </div>
                      <div className="flex items-center justify-between text-xs text-slate-400 font-mono pt-1">
                        <span>{msg.card_data.tasks_count} tasks planned</span>
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => navigate(`/goals/${msg.card_data?.goal_id}`)}
                          rightIcon={<ExternalLink className="w-3 h-3" />}
                        >
                          Workspace
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Card 2: Next Action */}
                  {msg.card_type === 'next_action' && (
                    <div className="p-3 rounded-xl bg-sky-950/30 border border-sky-500/30 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-mono font-bold text-sky-300 uppercase flex items-center space-x-1">
                          <CheckCircle2 className="w-3.5 h-3.5 text-sky-400" />
                          <span>Critical Path Focus</span>
                        </span>
                        <Badge variant="info">{msg.card_data.priority}</Badge>
                      </div>
                      <div className="font-semibold text-white text-sm">
                        {msg.card_data.title}
                      </div>
                      <div className="flex items-center justify-between pt-1">
                        <span className="text-xs text-slate-400 font-mono flex items-center space-x-1">
                          <Clock className="w-3 h-3" />
                          <span>{msg.card_data.estimated_minutes} min effort</span>
                        </span>
                        <Button
                          size="sm"
                          onClick={() => handleSendMessage('I finished the task')}
                          leftIcon={<CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />}
                        >
                          Mark Done
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Card 3: Plan Diff */}
                  {msg.card_type === 'plan_diff' && (
                    <div className="p-3 rounded-xl bg-slate-900 border border-emerald-500/30 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-emerald-400 uppercase flex items-center space-x-1">
                          <GitBranch className="w-3.5 h-3.5" />
                          <span>PLAN CHANGED DIFF</span>
                        </span>
                        <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/40">
                          v{msg.card_data.prev_version} &rarr; v{msg.card_data.new_version}
                        </span>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-center text-xs font-mono py-1">
                        <div className="p-1.5 rounded bg-slate-950 border border-slate-800">
                          <div className="text-emerald-400 font-bold">+{msg.card_data.added_count || 0}</div>
                          <div className="text-[10px] text-slate-500">Added</div>
                        </div>
                        <div className="p-1.5 rounded bg-slate-950 border border-slate-800">
                          <div className="text-sky-400 font-bold">&Delta;{msg.card_data.rescheduled_count || 0}</div>
                          <div className="text-[10px] text-slate-500">Rescheduled</div>
                        </div>
                        <div className="p-1.5 rounded bg-slate-950 border border-slate-800">
                          <div className="text-purple-400 font-bold">{msg.card_data.priority_count || 0}</div>
                          <div className="text-[10px] text-slate-500">Priorities</div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Card 4: Why Plan Changed */}
                  {msg.card_type === 'replanning_why' && (
                    <div className="p-3 rounded-xl bg-purple-950/20 border border-purple-500/30 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-purple-300 uppercase">
                          Root Cause Analysis
                        </span>
                        <Badge variant="warning">{msg.card_data.trigger_reason}</Badge>
                      </div>
                      <p className="text-xs text-slate-300 leading-relaxed">
                        {msg.card_data.explanation}
                      </p>
                    </div>
                  )}

                  {/* Card 5: Memory Stored */}
                  {msg.card_type === 'memory_stored' && (
                    <div className="p-3 rounded-xl bg-purple-950/30 border border-purple-500/30 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-purple-300 uppercase flex items-center space-x-1">
                          <Brain className="w-3.5 h-3.5 text-purple-400" />
                          <span>Persistent Memory Recorded</span>
                        </span>
                        <Badge variant="info">{msg.card_data.category}</Badge>
                      </div>
                      <p className="text-xs text-slate-200 italic">
                        "{msg.card_data.content}"
                      </p>
                      <div className="flex justify-end pt-1">
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => navigate('/memories')}
                          rightIcon={<ExternalLink className="w-3 h-3" />}
                        >
                          View in Memories
                        </Button>
                      </div>
                    </div>
                  )}

                  {/* Card 6: Blockers Diagnostic */}
                  {msg.card_type === 'blockers_diagnostic' && (
                    <div className="p-3 rounded-xl bg-rose-950/20 border border-rose-500/30 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-rose-300 uppercase flex items-center space-x-1">
                          <ShieldAlert className="w-3.5 h-3.5 text-rose-400" />
                          <span>Blocker Diagnostic</span>
                        </span>
                        <Badge variant={msg.card_data.blockers_count > 0 ? 'danger' : 'success'}>
                          {msg.card_data.deadline_risk?.toUpperCase()} RISK
                        </Badge>
                      </div>
                      <div className="text-xs text-slate-300">
                        {msg.card_data.recommended_action}
                      </div>
                    </div>
                  )}

                  {/* Card 7: Deadline Updated */}
                  {msg.card_type === 'deadline_updated' && (
                    <div className="p-3 rounded-xl bg-amber-950/20 border border-amber-500/30 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-amber-300 uppercase flex items-center space-x-1">
                          <Clock className="w-3.5 h-3.5 text-amber-400" />
                          <span>Deadline Updated</span>
                        </span>
                        <Badge variant="warning">{msg.card_data.formatted_date}</Badge>
                      </div>
                      <div className="text-xs font-semibold text-white">
                        {msg.card_data.goal_title}
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono">
                        Target date adjusted. Autonomous replanning has realigned your schedule.
                      </div>
                    </div>
                  )}

                  {/* Card 8: Goal Priority Updated */}
                  {msg.card_type === 'goal_priority_updated' && (
                    <div className="p-3 rounded-xl bg-indigo-950/20 border border-indigo-500/30 space-y-1.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-indigo-300 uppercase">
                          Priority Adjusted
                        </span>
                        <Badge variant="info">{msg.card_data.priority}</Badge>
                      </div>
                      <div className="text-xs font-semibold text-white">
                        {msg.card_data.title}
                      </div>
                    </div>
                  )}

                  {/* Card 9: Milestones View */}
                  {msg.card_type === 'milestones_view' && msg.card_data && (
                    <div className="p-3 rounded-xl bg-slate-900 border border-slate-700/60 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-slate-300 uppercase flex items-center space-x-1">
                          <GitBranch className="w-3.5 h-3.5 text-emerald-400" />
                          <span>Milestones ({msg.card_data?.goal_title})</span>
                        </span>
                      </div>
                      <div className="space-y-1.5 pt-1">
                        {msg.card_data?.milestones?.map((m: any, idx: number) => (
                          <div
                            key={idx}
                            className={`p-2 rounded-lg text-xs flex items-center justify-between ${
                              m.id === msg.card_data?.active_milestone_id
                                ? 'bg-emerald-950/40 border border-emerald-500/40 text-emerald-200'
                                : 'bg-slate-950 text-slate-300 border border-slate-800'
                            }`}
                          >
                            <span className="font-medium">{m.title}</span>
                            <span className="text-[10px] font-mono uppercase opacity-75">{m.status}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Card 10: Memories View */}
                  {msg.card_type === 'memories_view' && msg.card_data && (
                    <div className="p-3 rounded-xl bg-purple-950/20 border border-purple-500/30 space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-purple-300 uppercase flex items-center space-x-1">
                          <Brain className="w-3.5 h-3.5 text-purple-400" />
                          <span>User Context &amp; Memory</span>
                        </span>
                        <Badge variant="info">{msg.card_data?.count} items</Badge>
                      </div>
                      <div className="space-y-1.5 pt-1">
                        {msg.card_data?.memories?.map((mem: any, idx: number) => (
                          <div key={idx} className="p-2 rounded bg-slate-950/80 border border-purple-900/30 text-xs">
                            <span className="text-purple-400 font-mono text-[10px] uppercase font-bold mr-1.5">
                              [{mem.category}]
                            </span>
                            <span className="text-slate-200 italic">"{mem.content}"</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Card 11: Clarification Choice Options */}
                  {msg.card_type === 'clarification_choice' && msg.card_data && (
                    <div className="p-3 rounded-xl bg-sky-950/30 border border-sky-500/40 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-sky-300 uppercase">
                          Select An Option
                        </span>
                      </div>
                      <div className="grid grid-cols-1 gap-1.5">
                        {msg.card_data?.options?.map((opt: any, idx: number) => (
                          <button
                            key={idx}
                            onClick={() => handleSendMessage(opt.label)}
                            className="p-2.5 rounded-lg bg-slate-900 hover:bg-sky-900/40 border border-slate-700/80 hover:border-sky-400 text-left text-xs text-slate-100 transition-colors flex items-center justify-between"
                          >
                            <span className="font-semibold text-sky-200">{idx + 1}. {opt.label}</span>
                            {opt.description && (
                              <span className="text-[11px] text-slate-400 font-mono">{opt.description}</span>
                            )}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Loading Spinner Indicator */}
        {chatMutation.isPending && (
          <div className="flex items-center space-x-2 text-xs font-mono text-emerald-400 animate-pulse pl-1">
            <RefreshCw className="w-3.5 h-3.5 animate-spin" />
            <span>Agent Orchestrator executing live operation...</span>
          </div>
        )}

        {/* Error Alert State */}
        {chatMutation.isError && (
          <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-xs text-rose-300 flex items-center justify-between animate-fade-in">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>
                {chatMutation.error instanceof Error
                  ? chatMutation.error.message
                  : 'Agent orchestration failed. Please verify your connection or retry.'}
              </span>
            </div>
            <button
              onClick={() => chatMutation.reset()}
              className="text-[11px] underline font-mono text-rose-400 hover:text-rose-200 ml-2 shrink-0"
            >
              Dismiss
            </button>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* ========================================================================= */}
      {/* 3. QUICK CHIPS & INPUT COMPONENT                                          */}
      {/* ========================================================================= */}
      <div className="bg-slate-950 border-t border-slate-800 p-3 sm:p-4 space-y-3 shrink-0">
        {/* Active Clarification Prompt if pending */}
        {contextSummary?.pending_clarification && (
          <div className="p-2.5 rounded-xl bg-sky-950/40 border border-sky-500/40 space-y-1.5 animate-fadeIn">
            <div className="flex items-center justify-between text-xs text-sky-300 font-semibold">
              <span>{contextSummary.pending_clarification.prompt_message}</span>
              <button
                type="button"
                onClick={() => handleSendMessage('cancel')}
                className="text-[11px] text-slate-400 hover:text-rose-400 underline font-mono"
              >
                Cancel
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {contextSummary.pending_clarification.options.map((opt, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => handleSendMessage(opt.label)}
                  className="px-3 py-1.5 rounded-lg bg-sky-900/60 hover:bg-sky-800 text-sky-100 hover:text-white border border-sky-500/50 text-xs font-medium transition-colors flex items-center space-x-1.5 shadow-sm"
                >
                  <span className="w-4 h-4 rounded-full bg-sky-700 flex items-center justify-center text-[10px] font-mono">
                    {idx + 1}
                  </span>
                  <span>{opt.label}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Quick Suggestion Chips */}
        <div className="flex items-center space-x-1.5 overflow-x-auto pb-1 text-xs">
          <span className="text-[11px] font-mono text-slate-500 shrink-0">Quick:</span>
          {['Change the deadline to Friday', ...quickPrompts.slice(0, 4)].map((q, i) => (
            <button
              key={i}
              type="button"
              onClick={() => handleSendMessage(q)}
              className="px-2.5 py-1 rounded-full bg-slate-900 hover:bg-slate-800 text-slate-300 hover:text-white border border-slate-800 hover:border-emerald-500/40 text-[11px] font-mono whitespace-nowrap transition-colors"
            >
              {q}
            </button>
          ))}
        </div>

        {/* Input Bar Form */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="flex items-end space-x-2"
        >
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask agent: 'What should I do next?', 'I only have 1 hour today', 'What changed?'..."
              rows={1}
              className="w-full bg-slate-900 border border-slate-700/80 rounded-xl px-4 py-2.5 text-xs sm:text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 resize-none max-h-32"
            />
          </div>

          <Button
            type="submit"
            disabled={!inputMessage.trim() || chatMutation.isPending}
            className="shrink-0 h-10 px-4"
          >
            <Send className="w-4 h-4" />
          </Button>
        </form>
      </div>

      {/* Clear / Reset Chat Confirmation Modal */}
      <ConfirmDialog
        isOpen={isClearConfirmOpen}
        onClose={() => setIsClearConfirmOpen(false)}
        onConfirm={handleClearChat}
        title="Reset Conversation Session"
        message="Are you sure you want to reset this chat conversation? The current message thread will be cleared from your view, and a fresh orchestration session will be started."
        confirmText="Reset Chat"
        variant="warning"
      />
    </div>
  );
};
