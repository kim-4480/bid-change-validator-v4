import { apiFetch, ApiError } from './api';

export type HistoryJob = {
  id: string;
  notice_id: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  attempts: number;
  next_attempt_at: string;
  last_error: string | null;
  updated_at: string;
};

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `요청 실패 (${response.status})`, response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<T>;
}

export async function listHistoryJobs(): Promise<HistoryJob[]> {
  return readResponse<HistoryJob[]>(await apiFetch('/api/v1/admin/history-jobs?limit=50'));
}

export async function retryHistoryJob(jobId: string): Promise<HistoryJob> {
  return readResponse<HistoryJob>(await apiFetch(`/api/v1/admin/history-jobs/${encodeURIComponent(jobId)}/retry`, {
    method: 'POST',
  }));
}
