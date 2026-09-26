import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { Spinner } from "../ui/Spinner";

interface PublicRouteProps {
  children: React.ReactElement;
}

export const PublicRoute: React.FC<PublicRouteProps> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center space-y-3">
        <Spinner size="lg" />
      </div>
    );
  }

  if (isAuthenticated) {
    // Redirect to previously requested page if available, or default to /dashboard
    const origin =
      (location.state as { from?: { pathname: string } })?.from?.pathname ||
      "/dashboard";
    return <Navigate to={origin} replace />;
  }

  return children;
};
