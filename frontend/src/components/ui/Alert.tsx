import React from "react";
import {
  AlertCircle,
  AlertTriangle,
  CheckCircle2,
  Info,
  X,
} from "lucide-react";
import { cn } from "../../utils/cn";

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "info" | "success" | "warning" | "error";
  title?: string;
  onDismiss?: () => void;
}

export const Alert: React.FC<AlertProps> = ({
  className,
  variant = "info",
  title,
  onDismiss,
  children,
  ...props
}) => {
  const variants = {
    info: {
      container: "bg-blue-950/40 border-blue-800/60 text-blue-200",
      icon: <Info className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />,
    },
    success: {
      container: "bg-emerald-950/40 border-emerald-800/60 text-emerald-200",
      icon: (
        <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
      ),
    },
    warning: {
      container: "bg-amber-950/40 border-amber-800/60 text-amber-200",
      icon: (
        <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
      ),
    },
    error: {
      container: "bg-rose-950/40 border-rose-800/60 text-rose-200",
      icon: <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />,
    },
  };

  const current = variants[variant];

  return (
    <div
      role="alert"
      className={cn(
        "rounded-lg border p-4 flex items-start space-x-3 text-sm shadow-sm",
        current.container,
        className,
      )}
      {...props}
    >
      {current.icon}
      <div className="flex-1 space-y-0.5">
        {title && <h5 className="font-semibold leading-tight">{title}</h5>}
        <div className="text-xs leading-relaxed opacity-90">{children}</div>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="text-current opacity-60 hover:opacity-100 transition-opacity p-0.5"
          aria-label="Dismiss alert"
        >
          <X className="w-4 h-4" />
        </button>
      )}
    </div>
  );
};
