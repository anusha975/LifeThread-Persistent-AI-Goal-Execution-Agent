import React from 'react';
import { AlertTriangle, AlertCircle, Info, LucideIcon } from 'lucide-react';
import { Modal } from './Modal';
import { Button } from './Button';
import { cn } from '../../utils/cn';

export type ConfirmVariant = 'danger' | 'warning' | 'primary';

export interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: string;
  message?: string;
  confirmLabel?: string;
  confirmText?: string;
  cancelLabel?: string;
  isLoading?: boolean;
  variant?: ConfirmVariant;
  icon?: LucideIcon;
}

export const ConfirmDialog: React.FC<ConfirmDialogProps> = ({
  isOpen,
  onClose,
  onConfirm,
  title,
  description,
  message,
  confirmLabel,
  confirmText,
  cancelLabel = 'Cancel',
  isLoading = false,
  variant = 'danger',
  icon: CustomIcon,
}) => {
  const resolvedDesc = description || message || '';
  const resolvedConfirmLabel = confirmLabel || confirmText || 'Confirm';
  const isDanger = variant === 'danger';
  const isWarning = variant === 'warning';

  const DefaultIcon = isDanger ? AlertTriangle : isWarning ? AlertCircle : Info;
  const Icon = CustomIcon || DefaultIcon;

  const iconColorClass = isDanger
    ? 'text-rose-400 bg-rose-500/10 border-rose-500/30'
    : isWarning
    ? 'text-amber-400 bg-amber-500/10 border-amber-500/30'
    : 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30';

  const buttonVariant = isDanger ? 'danger' : isWarning ? 'outline' : 'primary';

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title=""
      maxWidth="sm"
    >
      <div className="text-center pt-2 pb-1 space-y-4">
        {/* Ambient Badge Icon */}
        <div className="flex justify-center">
          <div
            className={cn(
              'w-12 h-12 rounded-2xl border flex items-center justify-center shadow-lg transition-transform',
              iconColorClass
            )}
          >
            <Icon className="w-6 h-6 stroke-[1.75]" aria-hidden="true" />
          </div>
        </div>

        {/* Text Content */}
        <div className="space-y-1.5 px-2">
          <h3 className="text-base font-semibold text-white tracking-tight">
            {title}
          </h3>
          <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">
            {resolvedDesc}
          </p>
        </div>

        {/* Actions */}
        <div className="flex items-center justify-center gap-3 pt-3 border-t border-slate-800/80">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClose}
            disabled={isLoading}
            className="w-full sm:w-auto"
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant={buttonVariant}
            size="sm"
            onClick={onConfirm}
            isLoading={isLoading}
            className="w-full sm:w-auto"
          >
            {resolvedConfirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  );
};
