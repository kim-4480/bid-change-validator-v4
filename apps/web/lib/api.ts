const configuredApiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://localhost:8000';
export const API_BASE_URL = configuredApiBase.replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code: string,
  ) {
    super(message);
  }
}

/** 서버까지 닿지 못했을 때 화면에 나가는 문구. 어느 화면에서 실패하든 같은 말을 한다. */
export const NETWORK_ERROR_MESSAGE = '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.';

export function absoluteApiUrl(path: string) {
  return /^https?:\/\//.test(path) ? path : `${API_BASE_URL}${path}`;
}

/** Share the existing HttpOnly session only with the configured API origin.
 * Does not persist tokens, retry writes, or send credentials to document hosts.
 */
export async function apiFetch(path: string, init: RequestInit = {}) {
  const url = absoluteApiUrl(path);
  const base = new URL(API_BASE_URL, typeof window === 'undefined' ? 'http://localhost' : window.location.origin);
  const target = new URL(url, base);
  try {
    return await fetch(url, { ...init, credentials: target.origin === base.origin ? 'include' : 'omit' });
  } catch {
    // fetch가 던지는 TypeError('Failed to fetch')는 서버까지 닿지 못했다는 뜻이다.
    // 원문을 그대로 화면에 올리면 사용자가 읽을 수 없으므로 여기서 한 번만 바꾼다.
    // status 0은 HTTP 응답 자체가 없었음을 뜻한다.
    throw new ApiError(NETWORK_ERROR_MESSAGE, 0, 'NETWORK_ERROR');
  }
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, {
    ...init,
    credentials: 'include',
    headers,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error?: { message?: string; code?: string };
    } | null;
    throw new ApiError(
      payload?.error?.message ?? `요청에 실패했습니다. (${response.status})`,
      response.status,
      payload?.error?.code ?? 'HTTP_ERROR',
    );
  }
  return response.json() as Promise<T>;
}

export type NoticeDocument = {
  id: string;
  document_order: number;
  name: string;
  viewer_type: string;
  render_source_url: string;
  text_url: string;
  preview_url: string | null;
  file_size_bytes: number | null;
  extraction_status: string;
  extracted_char_count: number | null;
};

export type ProposalDocument = {
  id: string;
  case_id: string;
  document_order: number;
  role: string;
  name: string;
  viewer_type: string;
  render_source_url: string;
  text_url: string;
  preview_url: string | null;
  file_size_bytes: number;
  extraction_status: string;
  extracted_char_count: number | null;
};

export type ViewableDocument = NoticeDocument | ProposalDocument;

export type BidNoticeVersion = {
  id: string;
  version_number: number;
  bid_notice_order: string;
  is_current: boolean;
  notice_kind: string | null;
  registration_type: string | null;
  is_reannouncement: boolean;
  posted_at: string | null;
  changed_at: string | null;
  bid_started_at: string | null;
  bid_closed_at: string | null;
  opened_at: string | null;
  allocated_budget: number | null;
  estimated_price: number | null;
  contract_method: string | null;
  change_reason: string | null;
  detail_url: string | null;
  collected_at: string;
  documents: NoticeDocument[];
};

export type BidNoticeSummary = {
  id: string;
  bid_notice_no: string;
  title: string;
  business_type: string;
  notice_kind: string | null;
  announcing_institution_code: string | null;
  announcing_institution_name: string | null;
  demanding_institution_code: string | null;
  demanding_institution_name: string | null;
  first_seen_at: string;
  last_seen_at: string;
  current_version: number;
};

export type BidNoticeDetail = BidNoticeSummary & {
  latest: BidNoticeVersion;
};

export type PreflightCase = {
  id: string;
  company_id: string | null;
  notice_id: string;
  bid_notice_no: string;
  notice_title: string;
  title: string;
  status: string;
  baseline_version_number: number | null;
  current_version_number: number;
  documents: ProposalDocument[];
  created_at: string;
  updated_at: string;
};

export type NoticeDocumentText = {
  document_id: string;
  name: string;
  extraction_status: string;
  extractor: string | null;
  char_count: number | null;
  text_sha256: string | null;
  text: string | null;
  blocks: Array<Record<string, unknown>> | null;
};

type ListResponse<T> = {
  total: number;
  limit: number;
  offset: number;
  items: T[];
};

export function listNotices(query = '') {
  const search = new URLSearchParams({ limit: '100' });
  if (query.trim()) search.set('q', query.trim());
  return apiRequest<ListResponse<BidNoticeSummary>>(`/api/v1/notices?${search}`);
}

export function getNotice(noticeId: string) {
  return apiRequest<BidNoticeDetail>(`/api/v1/notices/${noticeId}`);
}

export function getNoticeVersions(noticeId: string) {
  return apiRequest<BidNoticeVersion[]>(`/api/v1/notices/${noticeId}/versions`);
}

export function listPreflightCases(companyId?: string) {
  /*
    company_id를 같이 보낸다. 백엔드는 로그인 사용자가 있을 때만 회사로 거르는데,
    auth_required=false로 띄우면 회사 구분 없이 최근 100건이 잘려서 온다.
    그러면 100칸을 다른 회사 Case가 채워, 우리 회사 기존 검토 건이 목록 밖으로 밀린다.
  */
  const search = new URLSearchParams({ limit: '100' });
  if (companyId) search.set('company_id', companyId);
  return apiRequest<ListResponse<PreflightCase>>(`/api/v1/preflight-cases?${search}`);
}

/**
 * 공고 한 건의 기존 검토 건만 조회한다.
 * 목록 조회는 상위 100건까지라 그 밖에 있는 기존 건을 못 본다.
 * Case를 새로 만들기 직전에 이 공고만 콕 집어 확인하는 용도다. (#131 리뷰)
 */
export function findPreflightCasesByNotice(noticeId: string, companyId: string) {
  const search = new URLSearchParams({ notice_id: noticeId, company_id: companyId, limit: '100' });
  return apiRequest<ListResponse<PreflightCase>>(`/api/v1/preflight-cases?${search}`);
}

export function getPreflightCase(caseId: string) {
  return apiRequest<PreflightCase>(`/api/v1/preflight-cases/${caseId}`);
}

export function createPreflightCase(payload: {
  notice_id: string;
  baseline_version_number?: number;
  current_version_number: number;
  title: string;
}) {
  return apiRequest<PreflightCase>('/api/v1/preflight-cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function uploadProposalDocument(caseId: string, file: File) {
  const body = new FormData();
  body.append('role', 'PROPOSAL');
  body.append('file', file);
  return apiRequest<ProposalDocument>(`/api/v1/preflight-cases/${caseId}/documents`, {
    method: 'POST',
    body,
  });
}

export function getDocumentText(textUrl: string) {
  return apiRequest<NoticeDocumentText>(textUrl);
}
