import { apiClient } from "./apiClient";
import {
  MemoryCategory,
  MemoryCorrectionPayload,
  MemoryCreatePayload,
  MemoryListResponse,
  MemorySourceDetail,
  UserMemoryItem,
} from "../types/memory";

export interface ListMemoriesParams {
  category?: MemoryCategory;
  goalId?: string;
  query?: string;
  limit?: number;
  offset?: number;
}

export const memoryService = {
  async listMemories(params?: ListMemoriesParams): Promise<MemoryListResponse> {
    const query = new URLSearchParams();
    if (params?.category) query.append("category", params.category);
    if (params?.goalId) query.append("goal_id", params.goalId);
    if (params?.query) query.append("query", params.query);
    if (params?.limit) query.append("limit", params.limit.toString());
    if (params?.offset) query.append("offset", params.offset.toString());

    const qs = query.toString();
    const endpoint = qs ? `/memories?${qs}` : "/memories";
    return apiClient.get<MemoryListResponse>(endpoint);
  },

  async getMemory(memoryId: string): Promise<UserMemoryItem> {
    return apiClient.get<UserMemoryItem>(`/memories/${memoryId}`);
  },

  async correctMemory(
    memoryId: string,
    payload: MemoryCorrectionPayload,
  ): Promise<UserMemoryItem> {
    return apiClient.patch<UserMemoryItem>(`/memories/${memoryId}`, payload);
  },

  async deleteMemory(
    memoryId: string,
  ): Promise<{ success: boolean; memory_id: string }> {
    return apiClient.delete<{ success: boolean; memory_id: string }>(
      `/memories/${memoryId}`,
    );
  },

  async inspectSource(memoryId: string): Promise<MemorySourceDetail> {
    return apiClient.get<MemorySourceDetail>(`/memories/${memoryId}/source`);
  },

  async createMemory(payload: MemoryCreatePayload): Promise<UserMemoryItem> {
    return apiClient.post<UserMemoryItem>("/memories", payload);
  },
};
