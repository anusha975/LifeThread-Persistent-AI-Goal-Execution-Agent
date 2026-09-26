import React from 'react';
import { cn } from '../../utils/cn';

export interface SpinnerProps extends React.HTMLAttributes<HTMLDivElement> {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  variant?: 'emerald' | 'slate' | 'white';
}

export const Spinner: React.FC<SpinnerProps> = ({
  className,
  size = 'md',
  variant = 'emerald',
  ...props
}) => {
  const sizes = {
    sm: 'w-4 h-4 border-2',
    md: 'w-6 h-6 border-2',
    lg: 'w-8 h-8 border-3',
    xl: 'w-12 h-12 border-4',
  };

  const variants = {
    emerald: 'border-emerald-500/20 border-t-emerald-400',
    slate: 'border-slate-700 border-t-slate-300',
    white: 'border-white/20 border-t-white',
  };

  return (
    <div
      role="status"
      aria-label="loading"
      className={cn('rounded-full animate-spin', sizes[size], variants[variant], className)}
      {...props}
    />
  );
};
