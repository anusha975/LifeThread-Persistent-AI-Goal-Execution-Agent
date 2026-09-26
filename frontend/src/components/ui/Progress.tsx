import React from "react";
import { cn } from "../../utils/cn";

export interface ProgressProps extends React.HTMLAttributes<HTMLDivElement> {
  value: number; // 0 to 100
  max?: number;
  variant?: "emerald" | "blue" | "amber" | "rose" | "gradient";
  size?: "sm" | "md" | "lg";
  showLabel?: boolean;
}

export const Progress: React.FC<ProgressProps> = ({
  value,
  max = 100,
  variant = "emerald",
  size = "md",
  showLabel = false,
  className,
  ...props
}) => {
  const percentage = Math.min(
    100,
    Math.max(0, Math.round((value / max) * 100)),
  );

  const variants = {
    emerald: "bg-emerald-500 shadow-sm shadow-emerald-500/20",
    blue: "bg-blue-500 shadow-sm shadow-blue-500/20",
    amber: "bg-amber-500 shadow-sm shadow-amber-500/20",
    rose: "bg-rose-500 shadow-sm shadow-rose-500/20",
    gradient:
      "bg-gradient-to-r from-emerald-500 via-teal-400 to-cyan-500 shadow-md shadow-emerald-500/20",
  };

  const sizes = {
    sm: "h-1.5",
    md: "h-2.5",
    lg: "h-3.5",
  };

  return (
    <div className={cn("w-full space-y-1", className)} {...props}>
      {showLabel && (
        <div className="flex justify-between items-center text-xs font-mono text-slate-400">
          <span>Progress</span>
          <span className="font-semibold text-slate-200">{percentage}%</span>
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={percentage}
        aria-valuemin={0}
        aria-valuemax={100}
        className={cn(
          "w-full bg-slate-900 border border-slate-800/80 rounded-full overflow-hidden p-0.5",
          sizes[size],
        )}
      >
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500 ease-out",
            variants[variant],
          )}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
};
