export interface APIErrorDetail {
  code?: string;
  message: string;
  details?: Record<string, unknown> | null;
  request_id?: string;
}

export interface APIErrorResponse {
  error?: APIErrorDetail;
  detail?: string | Array<{ msg: string; loc: string[] }>;
  message?: string;
}

export class APIError extends Error {
  public status: number;
  public code?: string;
  public details?: Record<string, unknown> | null;
  public requestId?: string;

  constructor(
    status: number,
    message: string,
    code?: string,
    details?: Record<string, unknown> | null,
    requestId?: string,
  ) {
    super(message);
    this.name = "APIError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.requestId = requestId;
  }
}
