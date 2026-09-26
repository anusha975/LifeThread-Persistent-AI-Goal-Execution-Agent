import React, { Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { AuthProvider } from './context/AuthContext';
import { ErrorBoundary } from './components/layout/ErrorBoundary';
import { AppShell } from './components/layout/AppShell';
import { ProtectedRoute } from './components/layout/ProtectedRoute';
import { PublicRoute } from './components/layout/PublicRoute';

// Code-split page components for minimal initial bundle size and rapid loading
const LoginPage = React.lazy(() => import('./pages/LoginPage').then(m => ({ default: m.LoginPage })));
const RegisterPage = React.lazy(() => import('./pages/RegisterPage').then(m => ({ default: m.RegisterPage })));
const DashboardPage = React.lazy(() => import('./pages/DashboardPage').then(m => ({ default: m.DashboardPage })));
const GoalsPage = React.lazy(() => import('./pages/GoalsPage').then(m => ({ default: m.GoalsPage })));
const GoalDetailPage = React.lazy(() => import('./pages/GoalDetailPage').then(m => ({ default: m.GoalDetailPage })));
const AgentActivityPage = React.lazy(() => import('./pages/AgentActivityPage').then(m => ({ default: m.AgentActivityPage })));
const MemoryContextPage = React.lazy(() => import('./pages/MemoryContextPage').then(m => ({ default: m.MemoryContextPage })));
const AssistantPage = React.lazy(() => import('./pages/AssistantPage').then(m => ({ default: m.AssistantPage })));
const NotFoundPage = React.lazy(() => import('./pages/NotFoundPage').then(m => ({ default: m.NotFoundPage })));

function PageLoadingFallback() {
  return (
    <div className="flex h-screen items-center justify-center bg-slate-900 text-slate-300">
      <div className="flex items-center space-x-3">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
        <span className="text-sm font-medium">Loading LifeThread...</span>
      </div>
    </div>
  );
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 2, // 2 minutes
      retry: (failureCount, error: unknown) => {
        // Do not retry 401, 403, 404
        if (
          error &&
          typeof error === 'object' &&
          'status' in error &&
          (error.status === 401 || error.status === 403 || error.status === 404)
        ) {
          return false;
        }
        return failureCount < 2;
      },
      refetchOnWindowFocus: false,
    },
  },
});

export function App(): React.ReactElement {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <BrowserRouter>
            <Suspense fallback={<PageLoadingFallback />}>
              <Routes>
                {/* Public Unauthenticated Routes */}
                <Route
                  path="/login"
                  element={
                    <PublicRoute>
                      <LoginPage />
                    </PublicRoute>
                  }
                />
                <Route
                  path="/register"
                  element={
                    <PublicRoute>
                      <RegisterPage />
                    </PublicRoute>
                  }
                />

                {/* Protected Authenticated Routes with Shell */}
                <Route
                  path="/"
                  element={
                    <ProtectedRoute>
                      <AppShell />
                    </ProtectedRoute>
                  }
                >
                  <Route index element={<Navigate to="/dashboard" replace />} />
                  <Route path="dashboard" element={<DashboardPage />} />
                  <Route path="goals" element={<GoalsPage />} />
                  <Route path="goals/:id" element={<GoalDetailPage />} />
                  <Route path="activity" element={<AgentActivityPage />} />
                  <Route path="memories" element={<MemoryContextPage />} />
                  <Route path="assistant" element={<AssistantPage />} />
                  <Route path="chat" element={<Navigate to="/assistant" replace />} />
                </Route>

                {/* Fallback 404 Route */}
                <Route path="*" element={<NotFoundPage />} />
              </Routes>
            </Suspense>
          </BrowserRouter>
        </AuthProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
