import React from "react";
import { LucideIcon } from "lucide-react";
import { Button } from "./Button";
import { cn } from "../../utils/cn";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  actionIcon?: React.ReactNode;
  action?: {
    label: string;
    onClick: () => void;
    icon?: LucideIcon;
  };
  secondaryActionLabel?: string;
  onSecondaryAction?: () => void;
  secondaryAction?: {
    label: string;
    onClick: () => void;
  };
  className?: string;
  variant?: "default" | "card" | "compact";
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  actionIcon,
  action,
  secondaryActionLabel,
  onSecondaryAction,
  secondaryAction,
  className,
  variant = "default",
}) => {
  const resolvedActionLabel = action?.label || actionLabel;
  const resolvedOnAction = action?.onClick || onAction;
  const ActionIcon = action?.icon;
  const resolvedActionIcon = ActionIcon ? (
    <ActionIcon className="w-4 h-4" />
  ) : (
    actionIcon
  );

  const resolvedSecLabel = secondaryAction?.label || secondaryActionLabel;
  const resolvedOnSec = secondaryAction?.onClick || onSecondaryAction;
  const isCard = variant === "card";
  const isCompact = variant === "compact";

  return (
    <div
      role="status"
      aria-label={title}
      className={cn(
        "flex flex-col items-center justify-center text-center transition-all",
        isCompact ? "py-8 px-4" : "py-12 px-6",
        isCard &&
          "rounded-2xl border border-slate-800/80 bg-slate-900/40 backdrop-blur-sm",
        className,
      )}
    >
      <div className="relative mb-4">
        {/* Subtle radial ambient glow */}
        <div className="absolute inset-0 bg-emerald-500/10 blur-xl rounded-full transform scale-150" />
        <div className="relative w-12 h-12 sm:w-14 sm:h-14 rounded-2xl bg-gradient-to-br from-slate-800 to-slate-900 border border-slate-700/60 shadow-lg flex items-center justify-center text-emerald-400">
          <Icon
            className="w-6 h-6 sm:w-7 sm:h-7 stroke-[1.75]"
            aria-hidden="true"
          />
        </div>
      </div>

      <h3 className="text-base sm:text-lg font-semibold text-white tracking-tight mb-1.5 max-w-md">
        {title}
      </h3>
      <p className="text-xs sm:text-sm text-slate-400 max-w-sm sm:max-w-md leading-relaxed mb-6">
        {description}
      </p>

      {(resolvedActionLabel || resolvedSecLabel) && (
        <div className="flex flex-wrap items-center justify-center gap-3">
          {resolvedActionLabel && resolvedOnAction && (
            <Button
              onClick={resolvedOnAction}
              variant="primary"
              size={isCompact ? "sm" : "md"}
              leftIcon={resolvedActionIcon}
            >
              {resolvedActionLabel}
            </Button>
          )}
          {resolvedSecLabel && resolvedOnSec && (
            <Button
              onClick={resolvedOnSec}
              variant="outline"
              size={isCompact ? "sm" : "md"}
            >
              {resolvedSecLabel}
            </Button>
          )}
        </div>
      )}
    </div>
  );
};
