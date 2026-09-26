import { APIError, APIErrorResponse } from "../types/api";

const TOKEN_KEY = "lifethread_token";
const REFRESH_TOKEN_KEY = "lifethread_refresh_token";

export const storage = {
  getToken: (): string | null => localStorage.getItem(TOKEN_KEY),
  setToken: (token: string): void => localStorage.setItem(TOKEN_KEY, token),
  removeToken: (): void => localStorage.removeItem(TOKEN_KEY),
  getRefreshToken: (): string | null => localStorage.getItem(REFRESH_TOKEN_KEY),
  setRefreshToken: (token: string): void =>
    localStorage.setItem(REFRESH_TOKEN_KEY, token),
  removeRefreshToken: (): void => localStorage.removeItem(REFRESH_TOKEN_KEY),
  clear: (): void => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};

type AuthChangeCallback = (isAuthenticated: boolean) => void;
const authChangeListeners: Set<AuthChangeCallback> = new Set();

export function onAuthChange(cb: AuthChangeCallback): () => void {
  authChangeListeners.add(cb);
  return () => authChangeListeners.delete(cb);
}

function notifyAuthChange(isAuthenticated: boolean): void {
  authChangeListeners.forEach((cb) => {
    try {
      cb(isAuthenticated);
    } catch (e) {
      console.error("Error in auth change listener:", e);
    }
  });
}

let isRefreshing = false;
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise;
  }

  const refreshToken = storage.getRefreshToken();
  if (!refreshToken) {
    storage.clear();
    notifyAuthChange(false);
    return null;
  }

  isRefreshing = true;
  refreshPromise = (async () => {
    try {
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!response.ok) {
        throw new Error("Refresh token invalid");
      }

      const data = await response.json();
      storage.setToken(data.access_token);
      if (data.refresh_token) {
        storage.setRefreshToken(data.refresh_token);
      }
      return data.access_token;
    } catch {
      storage.clear();
      notifyAuthChange(false);
      return null;
    } finally {
      isRefreshing = false;
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

export interface RequestOptions extends RequestInit {
  skipAuth?: boolean;
}

async function parseError(response: Response): Promise<APIError> {
  const status = response.status;
  let code: string | undefined;
  let message = `Request failed with status ${status}`;
  let details: Record<string, unknown> | null = null;
  let requestId: string | undefined;

  try {
    const data: APIErrorResponse = await response.json();
    if (data.error) {
      code = data.error.code;
      message = data.error.message || message;
      details = data.error.details ?? null;
      requestId = data.error.request_id;
    } else if (typeof data.detail === "string") {
      message = data.detail;
    } else if (Array.isArray(data.detail)) {
      message = data.detail.map((d) => d.msg).join("; ");
      details = { validation_errors: data.detail };
    } else if (data.message) {
      message = data.message;
    }
  } catch {
    // Response body not JSON or empty
    message = response.statusText || message;
  }

  return new APIError(status, message, code, details, requestId);
}

export async function request<T>(
  endpoint: string,
  options: RequestOptions = {},
): Promise<T> {
  const { skipAuth = false, headers = {}, ...customConfig } = options;

  const defaultHeaders: Record<string, string> = {
    "Content-Type": "application/json",
  };

  const token = storage.getToken();
  if (token && !skipAuth) {
    defaultHeaders["Authorization"] = `Bearer ${token}`;
  }

  const url =
    endpoint.startsWith("http") || endpoint.startsWith("/api")
      ? endpoint
      : `/api/v1${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  const config: RequestInit = {
    ...customConfig,
    headers: {
      ...defaultHeaders,
      ...(headers as Record<string, string>),
    },
  };

  let response: Response;
  try {
    response = await fetch(url, config);
  } catch (networkError) {
    throw new APIError(
      0,
      networkError instanceof Error
        ? networkError.message
        : "Network connection error",
    );
  }

  // Handle 401 Unauthorized by attempting token refresh
  if (
    response.status === 401 &&
    !skipAuth &&
    !url.includes("/auth/login") &&
    !url.includes("/auth/refresh")
  ) {
    const newToken = await refreshAccessToken();
    if (newToken) {
      // Retry original request with new token
      const retryHeaders = {
        ...(config.headers as Record<string, string>),
        Authorization: `Bearer ${newToken}`,
      };
      const retryResponse = await fetch(url, {
        ...config,
        headers: retryHeaders,
      });
      if (!retryResponse.ok) {
        throw await parseError(retryResponse);
      }
      if (retryResponse.status === 204) {
        return undefined as unknown as T;
      }
      return (await retryResponse.json()) as T;
    }
  }

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as unknown as T;
  }

  return (await response.json()) as T;
}

export const apiClient = {
  get: <T>(url: string, options?: RequestOptions) =>
    request<T>(url, { ...options, method: "GET" }),
  post: <T>(url: string, body?: unknown, options?: RequestOptions) =>
    request<T>(url, {
      ...options,
      method: "POST",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  patch: <T>(url: string, body?: unknown, options?: RequestOptions) =>
    request<T>(url, {
      ...options,
      method: "PATCH",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  put: <T>(url: string, body?: unknown, options?: RequestOptions) =>
    request<T>(url, {
      ...options,
      method: "PUT",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }),
  delete: <T>(url: string, options?: RequestOptions) =>
    request<T>(url, { ...options, method: "DELETE" }),
};
