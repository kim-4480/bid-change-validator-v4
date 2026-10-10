import { apiFetch, ApiError } from './api';

export type ProcessingJob = {
  id: string;
  notice_version_id: string;
  stage: 'EXTRACT' | 'INDEX' | 'FEATURES' | 'ANALYZE';
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'SUPERSEDED';
  priority: number;
  attempts: number;
  retry_budget: number;
  next_attempt_at: string;
  last_error: string | null;
  approved_by_id: string | null;
  approved_at: string | null;
  updated_at: string;
};

export type ProcessingAttempt = {
  attempt_number: number;
  outcome: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

const BASE = '/api/v1/admin/processing-jobs';

async function read<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `요청 실패 (${response.status})`, response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<T>;
}

export async function listProcessingJobs(): Promise<ProcessingJob[]> {
  return read(await apiFetch(`${BASE}?limit=50`));
}

export async function listProcessingAttempts(id: string): Promise<ProcessingAttempt[]> {
  return read(await apiFetch(`${BASE}/${encodeURIComponent(id)}/attempts`));
}

export async function retryProcessingJob(id: string): Promise<ProcessingJob> {
  return read(await apiFetch(`${BASE}/${encodeURIComponent(id)}/retry`, { method: 'POST' }));
}

export async function approveProcessingAnalysis(versionId: string): Promise<ProcessingJob> {
  return read(await apiFetch(`${BASE}/versions/${encodeURIComponent(versionId)}/approve-analysis`, { method: 'POST' }));
}
