import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { Target, AlertTriangle } from 'lucide-react';
import { Button } from '../components/ui/Button';
import { Badge } from '../components/ui/Badge';
import { Alert } from '../components/ui/Alert';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/Card';
import { EmptyState } from '../components/ui/EmptyState';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';

describe('Frontend Core UI Components', () => {
  it('renders Button with text and handles variants', () => {
    render(<Button variant="primary">Launch Mission</Button>);
    const btn = screen.getByRole('button', { name: /launch mission/i });
    expect(btn).toBeInTheDocument();
  });

  it('renders Badge with custom label and variant', () => {
    render(<Badge variant="success">ACTIVE_PLAN</Badge>);
    expect(screen.getByText('ACTIVE_PLAN')).toBeInTheDocument();
  });

  it('renders Alert component with title and message', () => {
    render(
      <Alert variant="warning" title="Deadline Approaching">
        Your goal timeline has 24 hours remaining.
      </Alert>
    );
    expect(screen.getByText('Deadline Approaching')).toBeInTheDocument();
    expect(screen.getByText(/your goal timeline has 24 hours remaining/i)).toBeInTheDocument();
  });

  it('renders Card with header and content elements', () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Autonomous Agent Run</CardTitle>
        </CardHeader>
        <CardContent>
          <p>Trace ID: TRACE-999</p>
        </CardContent>
      </Card>
    );
    expect(screen.getByText('Autonomous Agent Run')).toBeInTheDocument();
    expect(screen.getByText('Trace ID: TRACE-999')).toBeInTheDocument();
  });

  it('renders EmptyState with accessible role, title, description and CTA', () => {
    const handleAction = vi.fn();
    render(
      <EmptyState
        icon={Target}
        title="No Goals Found"
        description="Create your first goal to begin execution."
        action={{
          label: 'Create Goal',
          onClick: handleAction,
        }}
      />
    );

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByText('No Goals Found')).toBeInTheDocument();
    expect(screen.getByText('Create your first goal to begin execution.')).toBeInTheDocument();

    const actionBtn = screen.getByRole('button', { name: /create goal/i });
    fireEvent.click(actionBtn);
    expect(handleAction).toHaveBeenCalledTimes(1);
  });

  it('renders ConfirmDialog and responds to confirm and cancel callbacks', () => {
    const handleConfirm = vi.fn();
    const handleClose = vi.fn();

    render(
      <ConfirmDialog
        isOpen={true}
        onClose={handleClose}
        onConfirm={handleConfirm}
        title="Delete Resource"
        message="Are you sure you want to delete this resource?"
        confirmText="Confirm Delete"
        variant="danger"
        icon={AlertTriangle}
      />
    );

    expect(screen.getByText('Delete Resource')).toBeInTheDocument();
    expect(screen.getByText('Are you sure you want to delete this resource?')).toBeInTheDocument();

    const cancelBtn = screen.getByRole('button', { name: /cancel/i });
    fireEvent.click(cancelBtn);
    expect(handleClose).toHaveBeenCalledTimes(1);

    const confirmBtn = screen.getByRole('button', { name: /confirm delete/i });
    fireEvent.click(confirmBtn);
    expect(handleConfirm).toHaveBeenCalledTimes(1);
  });
});
