import { apiFetch, ApiError } from './api';

export type RelevanceLabel = {
  id: string;
  company_id: string;
  notice_version_id: string;
  grade: number;
  rationale: string;
  subject_origin: 'REAL' | 'SYNTHETIC' | 'UNKNOWN';
  status: 'DRAFT' | 'APPROVED' | 'REOPENED';
  reviewer_id: string;
  reviewed_at: string;
  approved_by_id: string | null;
  approved_at: string | null;
  updated_at: string;
};

export type RelevanceReviewInput = Pick<RelevanceLabel, 'company_id' | 'notice_version_id' | 'grade' | 'rationale' | 'subject_origin'>;

export type RelevanceEvent = {
  id: string;
  label_id: string;
  actor_id: string;
  action: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown>;
  created_at: string;
};

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `요청 실패 (${response.status})`, response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<T>;
}

const BASE = '/api/v1/admin/relevance-labels';

export async function listRelevanceLabels(): Promise<RelevanceLabel[]> {
  return readResponse<RelevanceLabel[]>(await apiFetch(`${BASE}?limit=100`));
}

export async function submitRelevanceReview(input: RelevanceReviewInput): Promise<RelevanceLabel> {
  return readResponse<RelevanceLabel>(await apiFetch(BASE, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  }));
}

export async function approveRelevanceReview(id: string): Promise<RelevanceLabel> {
  return readResponse<RelevanceLabel>(await apiFetch(`${BASE}/${encodeURIComponent(id)}/approve`, { method: 'POST' }));
}

export async function reopenRelevanceReview(id: string): Promise<RelevanceLabel> {
  return readResponse<RelevanceLabel>(await apiFetch(`${BASE}/${encodeURIComponent(id)}/reopen`, { method: 'POST' }));
}

export async function listRelevanceEvents(id: string): Promise<RelevanceEvent[]> {
  return readResponse<RelevanceEvent[]>(await apiFetch(`${BASE}/${encodeURIComponent(id)}/events`));
}
