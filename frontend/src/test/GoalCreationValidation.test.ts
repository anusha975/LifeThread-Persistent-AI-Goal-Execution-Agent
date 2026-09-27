import { describe, it, expect, vi, beforeEach } from "vitest";
import { goalService, normalizePriorityForApi, formatDeadlineForApi } from "../services/goalService";
import { apiClient } from "../services/apiClient";
import { APIError } from "../types/api";

describe("Goal Creation & Validation Suite", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("normalizes priority strings to uppercase for backend Pydantic enum", () => {
    expect(normalizePriorityForApi("low")).toBe("LOW");
    expect(normalizePriorityForApi("medium")).toBe("MEDIUM");
    expect(normalizePriorityForApi("high")).toBe("HIGH");
    expect(normalizePriorityForApi("critical")).toBe("CRITICAL");
    expect(normalizePriorityForApi(null)).toBe("MEDIUM");
    expect(normalizePriorityForApi(undefined)).toBe("MEDIUM");
  });

  it("formats valid deadline to ISO UTC string", () => {
    const iso = formatDeadlineForApi("2026-10-15T14:30");
    expect(iso).toBeTruthy();
    expect(new Date(iso!).toISOString()).toBe(iso);
    expect(formatDeadlineForApi("")).toBeNull();
    expect(formatDeadlineForApi(null)).toBeNull();
  });

  it("rejects invalid deadline format with APIError", () => {
    expect(() => formatDeadlineForApi("not-a-real-date")).toThrow(APIError);
  });

  it("serializes goal payload with uppercase priority and valid deadline on createGoal", async () => {
    const postSpy = vi.spyOn(apiClient, "post").mockResolvedValue({
      id: "test-goal-id",
      user_id: "test-user-id",
      title: "AI Engineer Interview Preparation",
      objective: "Become interview-ready for an AI Engineer role within 10 days.",
      description: "Prepare core Python, SQL, machine learning, LLM, RAG, and system design topics.",
      status: "ACTIVE",
      priority: "MEDIUM",
      deadline: "2026-10-15T09:00:00.000Z",
      success_criteria: [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    const result = await goalService.createGoal({
      title: "  AI Engineer Interview Preparation  ",
      objective: "  Become interview-ready for an AI Engineer role within 10 days.  ",
      description: "Prepare core Python, SQL, machine learning, LLM, RAG, and system design topics.",
      priority: "medium",
      deadline: "2026-10-15T09:00:00.000Z",
    });

    expect(postSpy).toHaveBeenCalledTimes(1);
    const calledPayload = postSpy.mock.calls[0][1] as any;
    expect(calledPayload.title).toBe("AI Engineer Interview Preparation");
    expect(calledPayload.objective).toBe("Become interview-ready for an AI Engineer role within 10 days.");
    expect(calledPayload.priority).toBe("MEDIUM");
    expect(calledPayload.deadline).toBe("2026-10-15T09:00:00.000Z");
    expect(result.status).toBe("ACTIVE");
    expect(result.priority).toBe("MEDIUM");
  });

  it("extracts granular validation errors from 422 response instead of generic error", async () => {
    // Mock fetch returning FastAPI 422 validation response
    const mockValidationResponse = {
      error: {
        code: "VALIDATION_ERROR",
        message: "Request validation failed",
        details: [
          {
            loc: ["body", "priority"],
            msg: "Input should be 'LOW', 'MEDIUM', 'HIGH' or 'CRITICAL'",
            type: "enum",
          },
        ],
        request_id: "req-123",
      },
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => mockValidationResponse,
    } as Response);

    try {
      await apiClient.post("/goals", { priority: "medium" });
      expect.fail("Should have thrown APIError");
    } catch (err: any) {
      expect(err).toBeInstanceOf(APIError);
      expect(err.status).toBe(422);
      expect(err.message).toBe("priority: Input should be 'LOW', 'MEDIUM', 'HIGH' or 'CRITICAL'");
      expect(err.details).toEqual(mockValidationResponse.error.details);
    }
  });

  it("handles 401, 403, and 500 error responses with user-friendly messages", async () => {
    // 401
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ error: { code: "UNAUTHORIZED", message: "Token has expired" } }),
    } as Response);

    try {
      await apiClient.get("/goals");
    } catch (err: any) {
      expect(err.status).toBe(401);
      expect(err.message).toBe("Token has expired");
    }

    // 403
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ error: { code: "FORBIDDEN", message: "Forbidden" } }),
    } as Response);

    try {
      await apiClient.get("/goals");
    } catch (err: any) {
      expect(err.status).toBe(403);
      expect(err.message).toContain("Permission denied");
    }

    // 500
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ error: { code: "INTERNAL_SERVER_ERROR", message: "DB connection down" } }),
    } as Response);

    try {
      await apiClient.get("/goals");
    } catch (err: any) {
      expect(err.status).toBe(500);
      expect(err.message).toBe("An unexpected server error occurred. Please try again later.");
    }
  });
});
