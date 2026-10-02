import { apiFetch, ApiError } from '@/lib/api';

export type NoticeMatch = {
  notice_id: string;
  bid_notice_no: string;
  title: string;
  institution_name: string | null;
  version_number: number;
  analysis_run_id: string;
  analysis_status: string;
  overall_status: 'eligible' | 'ineligible' | 'insufficient_data';
  satisfied_count: number;
  unknown_count: number;
  unsatisfied_count: number;
  requirement_count: number;
  evidence_count: number;
  analyzed_at: string;
};

export type NoticeMatchResponse = {
  company_id: string;
  analyzed_notice_count: number;
  returned_count: number;
  items: NoticeMatch[];
  note: string;
};

export async function listNoticeMatches(companyId: string, limit = 50) {
  const response = await apiFetch(`/api/v1/companies/${companyId}/notice-matches?limit=${limit}`);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `매칭 조회에 실패했습니다. (${response.status})`, response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<NoticeMatchResponse>;
}
