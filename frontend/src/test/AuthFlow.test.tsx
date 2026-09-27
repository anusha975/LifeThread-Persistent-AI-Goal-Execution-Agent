import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "../context/AuthContext";
import { ProtectedRoute } from "../components/layout/ProtectedRoute";
import { PublicRoute } from "../components/layout/PublicRoute";
import { authService } from "../services/authService";
import { storage } from "../services/apiClient";
import { APIError } from "../types/api";

// Test component to trigger auth actions
function AuthTestConsumer() {
  const { user, isAuthenticated, isLoading, login, logout } = useAuth();

  return (
    <div>
      <div data-testid="auth-status">
        {isLoading ? "loading" : isAuthenticated ? "authenticated" : "unauthenticated"}
      </div>
      <div data-testid="user-email">{user?.email || "none"}</div>
      <button
        onClick={() => {
          login({ email: "user@example.com", password: "Password123!" }).catch(
            () => {},
          );
        }}
      >
        Trigger Login
      </button>
      <button onClick={() => logout()}>Trigger Logout</button>
    </div>
  );
}

describe("LifeThread Authentication Flow", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("CASE 1: Valid credentials -> login succeeds, token persisted, auth state updated", async () => {
    const mockUser = {
      id: "usr-123",
      email: "user@example.com",
      display_name: "Test User",
      timezone: "UTC",
      is_active: true,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    vi.spyOn(authService, "login").mockResolvedValue({
      access_token: "mock_jwt_access_token",
      refresh_token: "mock_jwt_refresh_token",
      token_type: "bearer",
      expires_in: 3600,
    });
    vi.spyOn(authService, "getMe").mockResolvedValue(mockUser);

    render(
      <AuthProvider>
        <AuthTestConsumer />
      </AuthProvider>
    );

    // Initial state without token should be unauthenticated
    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");
    });

    // Trigger login
    screen.getByRole("button", { name: /trigger login/i }).click();

    // After login, auth state becomes authenticated and user is populated
    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user-email")).toHaveTextContent("user@example.com");
    });

    expect(storage.getToken()).toBe("mock_jwt_access_token");
    expect(storage.getRefreshToken()).toBe("mock_jwt_refresh_token");
  });

  it("CASE 2: Invalid credentials -> stay unauthenticated, token not saved", async () => {
    vi.spyOn(authService, "login").mockRejectedValue(
      new APIError(401, "Incorrect email or password")
    );

    render(
      <AuthProvider>
        <AuthTestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");
    });

    screen.getByRole("button", { name: /trigger login/i }).click();

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("unauthenticated");
    });

    expect(storage.getToken()).toBeNull();
  });

  it("CASE 4: Refresh after successful login -> restores session from token", async () => {
    storage.setToken("existing_valid_token");
    const mockUser = {
      id: "usr-456",
      email: "returning@example.com",
      display_name: "Returning User",
      timezone: "UTC",
      is_active: true,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    vi.spyOn(authService, "getMe").mockResolvedValue(mockUser);

    render(
      <AuthProvider>
        <AuthTestConsumer />
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId("auth-status")).toHaveTextContent("authenticated");
      expect(screen.getByTestId("user-email")).toHaveTextContent("returning@example.com");
    });
  });

  it("CASE 5: ProtectedRoute redirects unauthenticated user to /login", async () => {
    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <Routes>
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <div>Protected Workspace Content</div>
                </ProtectedRoute>
              }
            />
            <Route path="/login" element={<div>Login Page Screen</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Login Page Screen")).toBeInTheDocument();
      expect(screen.queryByText("Protected Workspace Content")).not.toBeInTheDocument();
    });
  });

  it("CASE 6: Expired token on refresh -> clears storage and redirects to /login", async () => {
    storage.setToken("expired_stale_token");
    vi.spyOn(authService, "getMe").mockRejectedValue(
      new APIError(401, "Invalid token")
    );

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <Routes>
            <Route
              path="/dashboard"
              element={
                <ProtectedRoute>
                  <div>Protected Workspace Content</div>
                </ProtectedRoute>
              }
            />
            <Route path="/login" element={<div>Login Page Screen</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Login Page Screen")).toBeInTheDocument();
      expect(storage.getToken()).toBeNull();
    });
  });

  it("PublicRoute redirects authenticated user to /dashboard and avoids loop to /login", async () => {
    storage.setToken("valid_token");
    const mockUser = {
      id: "usr-789",
      email: "user@example.com",
      display_name: "Active User",
      timezone: "UTC",
      is_active: true,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    vi.spyOn(authService, "getMe").mockResolvedValue(mockUser);

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={["/login"]}>
          <Routes>
            <Route
              path="/login"
              element={
                <PublicRoute>
                  <div>Login Form</div>
                </PublicRoute>
              }
            />
            <Route path="/dashboard" element={<div>Dashboard Content</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    );

    await waitFor(() => {
      expect(screen.getByText("Dashboard Content")).toBeInTheDocument();
      expect(screen.queryByText("Login Form")).not.toBeInTheDocument();
    });
  });
});
