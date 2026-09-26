import { LoginPayload, RegisterPayload, TokenResponse, User } from '../types/auth';
import { apiClient, storage } from './apiClient';

export const authService = {
  async login(payload: LoginPayload): Promise<TokenResponse> {
    const data = await apiClient.post<TokenResponse>('/auth/login', payload, { skipAuth: true });
    storage.setToken(data.access_token);
    storage.setRefreshToken(data.refresh_token);
    return data;
  },

  async register(payload: RegisterPayload): Promise<User> {
    return apiClient.post<User>('/auth/register', payload, { skipAuth: true });
  },

  async getMe(): Promise<User> {
    return apiClient.get<User>('/auth/me');
  },

  async logout(): Promise<void> {
    const refreshToken = storage.getRefreshToken();
    try {
      if (refreshToken) {
        await apiClient.post('/auth/logout', { refresh_token: refreshToken });
      }
    } catch {
      // Continue client cleanup even if backend logout fails or token is expired
    } finally {
      storage.clear();
    }
  },
};
