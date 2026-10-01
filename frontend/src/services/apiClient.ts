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

/**
 * Resolves the backend API base URL:
 * 1. Checks VITE_API_URL or VITE_API_BASE_URL (configured via build/env)
 * 2. If running on deployed static hosting (e.g. *-frontend.*), dynamically derives the backend service URL
 * 3. Prevents deployed production frontends from calling localhost
 * 4. Corrects legacy or misconfigured URL (e.g. 'lifethread.onrender.com' instead of 'lifethread-backend.onrender.com')
 * 5. Returns empty string for local development with Vite dev proxy forwarding /api
 */
export function getApiBaseUrl(): string {
  let envUrl =
    (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_URL) ||
    (typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE_URL);

  if (typeof envUrl === "string") {
    envUrl = envUrl.trim().replace(/\/+$/, "");
  } else {
    envUrl = "";
  }

  // If in browser environment
  if (typeof window !== "undefined" && window.location) {
    const { protocol, hostname, port } = window.location;
    const isLocalhost = hostname === "localhost" || hostname === "127.0.0.1";

    // 1. If running in production (not localhost), never allow localhost/127.0.0.1 API URLs
    if (
      !isLocalhost &&
      (envUrl.includes("localhost") || envUrl.includes("127.0.0.1"))
    ) {
      envUrl = "";
    }

    // 2. If running on a deployed frontend host with '-frontend' (e.g. lifethread-frontend.onrender.com)
    if (!isLocalhost && hostname.includes("-frontend")) {
      const pairedBackendHost = hostname.replace("-frontend", "-backend");
      const pairedBackendUrl = `${protocol}//${pairedBackendHost}${port ? `:${port}` : ""}`;

      // If envUrl is empty, OR points to misconfigured legacy host without '-backend'
      // (such as 'https://lifethread.onrender.com' instead of 'https://lifethread-backend.onrender.com')
      if (
        !envUrl ||
        envUrl === `${protocol}//${hostname.replace("-frontend", "")}` ||
        envUrl.includes("://lifethread.onrender.com")
      ) {
        return pairedBackendUrl;
      }
    }

    // 3. If envUrl is set and valid, use it
    if (envUrl) {
      return envUrl;
    }

    // 4. Fallback dynamic derivation for generic 'frontend' hostnames
    if (!isLocalhost && hostname.includes("frontend")) {
      return `${protocol}//${hostname.replace("frontend", "backend")}${port ? `:${port}` : ""}`;
    }
  }

  return envUrl || "";
}

export function buildApiUrl(endpoint: string): string {
  if (endpoint.startsWith("http://") || endpoint.startsWith("https://")) {
    return endpoint;
  }
  const base = getApiBaseUrl();
  const normalized = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  const path = normalized.startsWith("/api")
    ? normalized
    : `/api/v1${normalized}`;
  return `${base}${path}`;
}

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
      const response = await fetch(buildApiUrl("/auth/refresh"), {
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
  let details: unknown = null;
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
      details = data.detail;
    } else if (data.message) {
      message = data.message;
    }

    // Granular 422 validation error formatting
    if (status === 422) {
      const valErrors: any[] | null = Array.isArray(details)
        ? details
        : Array.isArray((details as any)?.validation_errors)
          ? (details as any).validation_errors
          : Array.isArray(data.detail)
            ? data.detail
            : null;

      if (valErrors && valErrors.length > 0) {
        const errorStrings = valErrors
          .map((err: any) => {
            let field = "";
            if (Array.isArray(err.loc)) {
              field = err.loc
                .filter(
                  (p: string | number) =>
                    p !== "body" && p !== "query" && p !== "path",
                )
                .join(".");
            }
            let msg = err.msg || "Invalid value";
            if (typeof msg === "string" && msg.startsWith("Value error, ")) {
              msg = msg.replace("Value error, ", "");
            }
            return field ? `${field}: ${msg}` : msg;
          })
          .filter(Boolean);

        if (errorStrings.length > 0) {
          message = errorStrings.join("; ");
        }
      } else if (!message || message === "Request validation failed") {
        message = "Input validation failed. Please check the entered fields.";
      }
    } else if (status === 401) {
      message =
        data.error?.message &&
        !data.error.message.toLowerCase().includes("unauthorized")
          ? data.error.message
          : "Your session has expired or you are unauthenticated. Please sign in again.";
    } else if (status === 403) {
      message =
        data.error?.message &&
        !data.error.message.toLowerCase().includes("forbidden")
          ? data.error.message
          : "Permission denied. You do not have access to perform this operation.";
    } else if (status >= 500) {
      message = "An unexpected server error occurred. Please try again later.";
    }
  } catch {
    // Response body not JSON or empty (e.g., Render HTML error pages)
    if (status === 503) {
      message =
        "Backend service is currently suspended or spinning up. Please wait a moment and try again.";
    } else if (status === 404) {
      message = "API endpoint or requested resource not found.";
    } else if (status === 401) {
      message =
        "Session expired or authentication failed. Please sign in again.";
    } else if (status === 403) {
      message =
        "Permission denied. You do not have access to perform this action.";
    } else if (status >= 500) {
      message = "An unexpected server error occurred. Please try again later.";
    } else {
      message = response.statusText || message;
    }
  }

  if (typeof console !== "undefined" && console.error) {
    console.error(`[LifeThread API Error] ${status}: ${message}`, {
      code,
      details,
      requestId,
    });
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

  const url = buildApiUrl(endpoint);

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
    if (typeof console !== "undefined" && console.error) {
      console.error(
        `[LifeThread Network Error] Failed to reach backend API at: ${url}`,
        {
          method: config.method || "GET",
          error:
            networkError instanceof Error
              ? networkError.message
              : String(networkError),
        },
      );
    }
    throw new APIError(
      0,
      networkError instanceof Error &&
        networkError.message !== "Failed to fetch" &&
        networkError.message !== "Load failed"
        ? networkError.message
        : "Unable to connect to the LifeThread backend service. Please check your network connection or try again in a few moments.",
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
    const error = await parseError(response);
    if (typeof console !== "undefined" && console.warn) {
      console.warn(
        `[LifeThread API Warning] ${response.status} from ${url}:`,
        error.message,
      );
    }
    throw error;
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
