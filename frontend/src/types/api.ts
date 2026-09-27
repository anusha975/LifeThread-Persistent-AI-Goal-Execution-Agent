export interface APIErrorDetail {
  code?: string;
  message: string;
  details?: unknown;
  request_id?: string;
}

export interface APIErrorResponse {
  error?: APIErrorDetail;
  detail?: string | Array<{ msg: string; loc: (string | number)[] }>;
  message?: string;
}

export class APIError extends Error {
  public status: number;
  public code?: string;
  public details?: unknown;
  public requestId?: string;

  constructor(
    status: number,
    message: string,
    code?: string,
    details?: unknown,
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
