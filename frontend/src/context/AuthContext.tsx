import React, {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
} from "react";
import { AuthState, LoginPayload, RegisterPayload, User } from "../types/auth";
import { authService } from "../services/authService";
import { onAuthChange, storage } from "../services/apiClient";

interface AuthContextType extends AuthState {
  login: (payload: LoginPayload) => Promise<void>;
  register: (payload: RegisterPayload) => Promise<User>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(storage.getToken());
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const fetchCurrentUser = useCallback(async () => {
    const currentToken = storage.getToken();
    if (!currentToken) {
      setUser(null);
      setToken(null);
      setIsLoading(false);
      return;
    }

    try {
      const userData = await authService.getMe();
      setUser(userData);
      setToken(currentToken);
    } catch {
      storage.clear();
      setUser(null);
      setToken(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCurrentUser();

    // Listen to background auth changes (e.g. session expiration during API calls)
    const unsubscribe = onAuthChange((isAuthenticated) => {
      if (!isAuthenticated) {
        setUser(null);
        setToken(null);
      }
    });

    return () => unsubscribe();
  }, [fetchCurrentUser]);

  const login = async (payload: LoginPayload): Promise<void> => {
    try {
      const tokenResp = await authService.login(payload);
      storage.setToken(tokenResp.access_token);
      if (tokenResp.refresh_token) {
        storage.setRefreshToken(tokenResp.refresh_token);
      }
      const userData = await authService.getMe();
      setUser(userData);
      setToken(tokenResp.access_token);
    } catch (err) {
      storage.clear();
      setUser(null);
      setToken(null);
      throw err;
    }
  };

  const register = async (payload: RegisterPayload): Promise<User> => {
    return await authService.register(payload);
  };

  const logout = async (): Promise<void> => {
    try {
      await authService.logout();
    } finally {
      storage.clear();
      setUser(null);
      setToken(null);
    }
  };

  const refreshUser = async (): Promise<void> => {
    await fetchCurrentUser();
  };

  const value: AuthContextType = {
    user,
    token,
    isAuthenticated: Boolean(user && token),
    isLoading,
    login,
    register,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
