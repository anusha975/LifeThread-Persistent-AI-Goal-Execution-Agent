import React from 'react';
import { cn } from '../../utils/cn';

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?:
    | 'default'
    | 'success'
    | 'warning'
    | 'danger'
    | 'info'
    | 'active'
    | 'paused'
    | 'completed'
    | 'archived'
    | 'failed'
    | 'critical'
    | 'high'
    | 'medium'
    | 'low';
}

export const Badge: React.FC<BadgeProps> = ({ className, variant = 'default', children, ...props }) => {
  const variants: Record<string, string> = {
    default: 'bg-slate-800 text-slate-300 border-slate-700',
    info: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
    success: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    warning: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    danger: 'bg-rose-500/10 text-rose-400 border-rose-500/20',

    // Goal Statuses
    active: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    paused: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    completed: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    archived: 'bg-slate-800 text-slate-400 border-slate-700',
    failed: 'bg-rose-500/10 text-rose-400 border-rose-500/30',

    // Goal Priorities
    critical: 'bg-rose-500/15 text-rose-400 border-rose-500/40 font-semibold',
    high: 'bg-orange-500/15 text-orange-400 border-orange-500/30',
    medium: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
    low: 'bg-slate-800 text-slate-400 border-slate-700',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border capitalize tracking-wide',
        variants[variant] || variants.default,
        className
      )}
      {...props}
    >
      {children}
    </span>
  );
};
