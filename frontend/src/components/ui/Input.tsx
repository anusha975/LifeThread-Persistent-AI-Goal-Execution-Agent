import React from "react";
import { cn } from "../../utils/cn";

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  (
    { className, label, error, helperText, leftIcon, rightIcon, id, ...props },
    ref,
  ) => {
    const inputId = id || props.name || Math.random().toString(36).substring(7);

    return (
      <div className="w-full space-y-1.5">
        {label && (
          <label
            htmlFor={inputId}
            className="block text-xs font-medium uppercase tracking-wider text-slate-300"
          >
            {label}
          </label>
        )}
        <div className="relative rounded-lg shadow-sm">
          {leftIcon && (
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
              {leftIcon}
            </div>
          )}
          <input
            id={inputId}
            ref={ref}
            className={cn(
              "w-full bg-slate-900 border text-slate-100 placeholder-slate-500 rounded-lg px-3.5 py-2.5 text-sm transition-colors duration-150",
              "focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-transparent",
              "disabled:bg-slate-950 disabled:text-slate-600 disabled:border-slate-800 disabled:cursor-not-allowed",
              leftIcon ? "pl-10" : "pl-3.5",
              rightIcon ? "pr-10" : "pr-3.5",
              error
                ? "border-rose-500/80 focus:ring-rose-500 text-rose-200"
                : "border-slate-800 hover:border-slate-700",
              className,
            )}
            {...props}
          />
          {rightIcon && (
            <div className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-400">
              {rightIcon}
            </div>
          )}
        </div>
        {error && <p className="text-xs text-rose-400 font-medium">{error}</p>}
        {!error && helperText && (
          <p className="text-xs text-slate-500">{helperText}</p>
        )}
      </div>
    );
  },
);

Input.displayName = "Input";
