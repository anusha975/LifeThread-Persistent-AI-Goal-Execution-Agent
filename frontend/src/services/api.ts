export interface HealthData {
  status: string;
  service: string;
  version: string;
}

export interface ReadinessData {
  status: string;
  service: string;
  version: string;
  checks: Record<string, string>;
}

export async function fetchHealth(): Promise<HealthData> {
  const response = await fetch('/api/v1/health');
  if (!response.ok) {
    throw new Error(`Health check failed with status: ${response.status}`);
  }
  return response.json();
}

export async function fetchReadiness(): Promise<ReadinessData> {
  const response = await fetch('/api/v1/ready');
  if (!response.ok) {
    throw new Error(`Readiness check failed with status: ${response.status}`);
  }
  return response.json();
}
