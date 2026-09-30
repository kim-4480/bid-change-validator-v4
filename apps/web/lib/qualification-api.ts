import { apiFetch, ApiError, type PreflightCase } from '@/lib/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await apiFetch(path, { ...init, headers });
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

export type CompanySize = 'MICRO' | 'SMALL' | 'MEDIUM' | 'MID_SIZED' | 'LARGE' | 'NONE';

export type CompanyProfile = {
  id: string;
  name: string;
  business_registration_number: string | null;
  region_code: string | null;
  region_name: string | null;
  company_size: CompanySize;
  industries: Array<{ code: string; name: string; verified: boolean }>;
  staff: {
    total_count: number;
    verified: boolean;
    roles: Array<{ role_name: string; headcount: number; verified: boolean }>;
  } | null;
  performances: Array<{
    id: string;
    name: string;
    client_name: string | null;
    client_institution_code: string | null;
    amount: number;
    started_at: string | null;
    completed_at: string;
    description: string | null;
    fields: string[];
    verified: boolean;
    created_at: string;
    updated_at: string;
  }>;
  certifications: Array<{
    id: string;
    name: string;
    certificate_number: string | null;
    issuer_name: string | null;
    issued_at: string | null;
    expires_at: string | null;
    verified: boolean;
    created_at: string;
    updated_at: string;
  }>;
  created_at: string;
  updated_at: string;
};

export type CompanyCreatePayload = {
  name: string;
  business_registration_number?: string;
  region_code: string;
  region_name?: string;
  company_size: CompanySize;
  industry_codes: string[];
  staff: {
    total_count: number;
    verified: boolean;
    roles: Array<{ role_name: string; headcount: number; verified: boolean }>;
  };
};

export type MasterCode = { code: string; name: string; active: boolean };

export type CanonicalRequirement = {
  requirement_key: string;
  requirement_group_key: string | null;
  group_operator: 'ALL_OF' | 'ANY_OF' | null;
  notice_version_id: string;
  type: string;
  operator: string | null;
  value: string | number | null;
  unit: string | null;
  period_months: number | null;
  scope: Record<string, unknown>;
  /* 백엔드 QualificationRequirement에 있는데 빠져 있던 필드들. 판정 입력 비교에 쓴다. (#132 리뷰) */
  requirement_role: string;
  condition_complexity: string;
  required: boolean;
  raw: string;
  evidence_keys: string[];
};

export type QualificationAnalysisSummary = {
  id: string;
  notice_version_id: string;
  version_number: number;
  contract_version: string;
  status: 'SUCCEEDED' | 'PARTIAL' | 'FAILED';
  requirement_count: number;
  evidence_count: number;
  created_at: string;
};

/**
 * 구조화 검증에서 제외된 후보 원문. apps/api analysis_result.py의 DroppedRequirement 그대로다.
 * 필드는 raw · reason_code 둘뿐이다 — evidence_key나 location은 오지 않으므로 원문 링크는 만들 수 없다.
 */
export type DroppedReasonCode =
  | 'MISSING_RAW'
  | 'RAW_NOT_FOUND_IN_SOURCE'
  | 'DETAIL_NOT_FOUND_IN_SOURCE'
  | 'SOURCE_VALIDATION_FAILED';

export type DroppedRequirement = {
  raw: string;
  reason_code: DroppedReasonCode;
};

/**
 * 분석 진단. kind가 NOTICE_FACT인 것은 오류가 아니라 「공고에서 확인했지만 판정 대상이 아닌 사실」이다.
 * PIPELINE 경고와 같은 자리에 그리면 사용자가 오류로 읽는다.
 */
export type AnalysisDiagnostic = {
  code: string;
  severity: string;
  message: string;
  kind: 'PIPELINE' | 'NOTICE_FACT';
  details: Record<string, unknown>;
  evidence_keys: string[];
};

export type QualificationAnalysisRun = QualificationAnalysisSummary & {
  notice_id: string;
  analysis_kind: string;
  target_chunk_ids: string[];
  diagnostics: AnalysisDiagnostic[];
  dropped_requirements: DroppedRequirement[];
  requirements: CanonicalRequirement[];
  evidence: Array<{
    evidence_key: string;
    document_id: string;
    quote: string;
    location: EvidenceLocation;
  }>;
};

/**
 * 근거의 위치. 백엔드가 extracted_blocks를 기준으로 만든다.
 * HWP/HWPX에는 페이지가 없어서 page가 null인 경우가 정상이다.
 * 화면이 "3.2항 p.4"를 직접 조립하지 말고 display를 그대로 쓴다.
 */
export type EvidenceLocation = {
  block_start?: number | null;
  block_end?: number | null;
  page?: number | null;
  section_index?: number | null;
  paragraph_start?: number | null;
  paragraph_end?: number | null;
  source_line_start?: number | null;
  source_line_end?: number | null;
  clause_label?: string | null;
  display?: string | null;
};

export type QualificationJudgment = {
  judgment_key: string;
  requirement_key: string;
  status: 'SATISFIED' | 'UNSATISFIED' | 'UNKNOWN';
  basis_type: 'PROFILE' | 'USER_ANSWER' | 'NONE';
  evidence_held: boolean;
  reason_code: string;
  requires_evidence: boolean;
  requirement_evidence_keys: string[];
};

export type QualificationJudgmentRun = {
  id: string;
  preflight_case_id: string;
  analysis_run_id: string;
  company_id: string;
  notice_version_id: string;
  overall_status: 'eligible' | 'ineligible' | 'insufficient_data';
  rule_version: string;
  reference_date: string;
  analysis_status: string;
  profile_completeness: Record<string, boolean>;
  judgments: QualificationJudgment[];
  created_at: string;
};

export type QualificationJudgmentSummary = {
  id: string;
  analysis_run_id: string;
  company_id: string;
  notice_version_id: string;
  overall_status: 'eligible' | 'ineligible' | 'insufficient_data';
  rule_version: string;
  reference_date: string;
  analysis_status: string;
  judgment_count: number;
  unknown_count: number;
  unsatisfied_count: number;
  created_at: string;
};

export type QualificationQuestion = {
  requirement_key: string;
  requirement_type: string;
  question: string;
  raw_requirement: string;
  askable: boolean;
  askability_reason_code: string;
  askability_reason: string;
};

export type RequirementChange = {
  change_type: 'UNCHANGED' | 'MODIFIED' | 'ADDED' | 'REMOVED';
  identity: string;
  baseline_key: string | null;
  current_key: string | null;
  /*
    양쪽 차수의 요건 전체가 여기 이미 들어온다. 키만 주는 줄 알고 분석 상세를 따로 받아
    키로 이어붙이고 있었는데 그럴 필요가 없었다. (#132 리뷰)
  */
  baseline: CanonicalRequirement | null;
  current: CanonicalRequirement | null;
};

export type QualificationRevalidation = {
  id: string;
  changes: RequirementChange[];
  revalidated_keys: string[];
  result: QualificationJudgmentRun;
};

export function listCompanies() {
  return request<CompanyProfile[]>('/api/v1/companies');
}

export function createCompany(payload: CompanyCreatePayload) {
  return request<CompanyProfile>('/api/v1/companies', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateCompany(companyId: string, payload: Partial<CompanyCreatePayload>) {
  return request<CompanyProfile>(`/api/v1/companies/${companyId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export function searchIndustryCodes(query = '') {
  const search = new URLSearchParams({ limit: '20' });
  if (query.trim()) search.set('q', query.trim());
  return request<{ items: MasterCode[] }>(`/api/v1/master-codes/industries?${search}`);
}

export function createCompanyCertification(
  companyId: string,
  payload: {
    name: string;
    certificate_number?: string;
    issuer_name?: string;
    issued_at?: string;
    expires_at?: string;
    verified?: boolean;
  },
) {
  return request<CompanyProfile['certifications'][number]>(`/api/v1/companies/${companyId}/certifications`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createCompanyPerformance(
  companyId: string,
  payload: {
    name: string;
    client_name?: string;
    amount: number;
    completed_at: string;
    fields?: string[];
    verified?: boolean;
  },
) {
  return request<CompanyProfile['performances'][number]>(`/api/v1/companies/${companyId}/performances`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function createPreflightCaseWithCompany(payload: {
  notice_id: string;
  company_id: string;
  baseline_version_number?: number;
  current_version_number: number;
  title: string;
}) {
  return request<PreflightCase>('/api/v1/preflight-cases', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function listQualificationAnalyses(noticeId: string, versionNumber: number) {
  return request<QualificationAnalysisSummary[]>(
    `/api/v1/notices/${noticeId}/versions/${versionNumber}/qualification-analyses`,
  );
}

export function runQualificationAnalysis(noticeId: string, versionNumber: number) {
  return request<QualificationAnalysisRun>(
    `/api/v1/notices/${noticeId}/versions/${versionNumber}/qualification-analysis`,
    { method: 'POST' },
  );
}

export function getQualificationAnalysis(runId: string) {
  return request<QualificationAnalysisRun>(`/api/v1/qualification-analyses/${runId}`);
}

export function listQualificationJudgments(caseId: string) {
  return request<QualificationJudgmentSummary[]>(
    `/api/v1/preflight-cases/${caseId}/qualification-judgment-runs`,
  );
}

export function getQualificationJudgment(runId: string) {
  return request<QualificationJudgmentRun>(`/api/v1/qualification-judgment-runs/${runId}`);
}

export function runQualificationJudgment(caseId: string, analysisRunId: string) {
  return request<QualificationJudgmentRun>(`/api/v1/preflight-cases/${caseId}/qualification-judgments`, {
    method: 'POST',
    body: JSON.stringify({ analysis_run_id: analysisRunId }),
  });
}

export function listQualificationQuestions(caseId: string, sourceRunId: string) {
  const search = new URLSearchParams({ source_judgment_run_id: sourceRunId });
  return request<QualificationQuestion[]>(
    `/api/v1/preflight-cases/${caseId}/qualification-questions?${search}`,
  );
}

export function answerQualificationQuestion(
  caseId: string,
  payload: {
    source_judgment_run_id: string;
    requirement_key: string;
    satisfies_requirement: boolean;
    normalized_value?: string;
    evidence_held?: boolean;
  },
) {
  return request<{ result: QualificationJudgmentRun }>(
    `/api/v1/preflight-cases/${caseId}/qualification-answers`,
    {
      method: 'POST',
      body: JSON.stringify({ ...payload, apply_to_profile: false }),
    },
  );
}

export function runQualificationRevalidation(
  caseId: string,
  payload: {
    source_judgment_run_id: string;
    baseline_analysis_run_id?: string;
    current_analysis_run_id?: string;
  },
) {
  return request<QualificationRevalidation>(
    `/api/v1/preflight-cases/${caseId}/qualification-revalidation`,
    { method: 'POST', body: JSON.stringify(payload) },
  );
}
