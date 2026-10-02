import { apiFetch, ApiError } from './api';
import type { CopilotEnvelope } from './copilot-v31';
import type { EvidenceLocation, QualificationQuestion } from './qualification-api';

// Pydantic app/copilot/{chat,contracts,actions}.py is the source of truth.
export type CopilotIntent = 'QUALIFICATION_SUMMARY' | 'REQUIREMENT_EVIDENCE' | 'REQUIRED_CHECKS'
  | 'PROFILE_SNAPSHOT' | 'DOCUMENT_QA' | 'ACTION_REQUEST' | 'CHANGED_NOTICE' | 'UNKNOWN';
export type OverallStatus = 'eligible' | 'ineligible' | 'insufficient_data';
export type JudgmentStatus = 'SATISFIED' | 'UNSATISFIED' | 'UNKNOWN';
export type RequirementType = 'PERFORMANCE_AMOUNT' | 'PERFORMANCE_COUNT' | 'INDUSTRY' | 'REGION'
  | 'STAFF' | 'REGISTRATION_CERTIFICATION' | 'EXPERIENCE_FIELD' | 'COMPANY_SIZE';
export type QualificationRequirement = {
  requirement_key: string; requirement_group_key: string | null; group_operator: 'ALL_OF' | 'ANY_OF' | null;
  notice_version_id: string; type: RequirementType; operator: '>=' | '>' | '<=' | '<' | '=' | 'MATCH' | 'RANGE' | null;
  value: number | string | null; unit: string | null; period_months: number | null;
  scope: Record<string, unknown>; required: boolean; raw: string; confidence: number | null; evidence_keys: string[];
  /* 백엔드 contracts.py의 QualificationRequirement에 있는데 빠져 있던 필드. 판정 입력 비교에 쓴다. (#132 리뷰) */
  requirement_role: string; condition_complexity: string;
};
export type Evidence = {
  evidence_key: string; source_type: 'NOTICE_DOCUMENT' | 'PROPOSAL_DOCUMENT'; document_id: string;
  notice_version_id: string | null; case_id: string | null; chunk_id: string | null;
  location: EvidenceLocation; quote: string; source_sha256: string | null; extracted_text_sha256: string | null;
};
export type Judgment = {
  judgment_key: string; preflight_case_id: string; notice_version_id: string; requirement_key: string;
  status: JudgmentStatus; basis_type: 'PROFILE' | 'USER_ANSWER' | 'NONE'; evidence_held: boolean;
  reason_code: 'RULE_MATCH' | 'RULE_MISMATCH' | 'INSUFFICIENT_DATA' | 'NEEDS_REVIEW' | 'UNSUPPORTED_REQUIREMENT';
  requires_evidence: boolean; profile_refs: Record<string, string>[]; requirement_evidence_keys: string[];
  rule_version: string | null;
};
export type ProfileCompleteness = Record<'region' | 'company_size' | 'industries' | 'staff_total'
  | 'staff_roles' | 'performances' | 'certifications', boolean>;
export type ProductProvenance = {
  case_id: string; notice_id: string; notice_version_id: string; version_number: number; company_id: string;
  analysis_run_id: string; judgment_run_id: string; analysis_status: 'SUCCEEDED' | 'PARTIAL'; rule_version: string;
};
export type QualificationSummary = {
  provenance: ProductProvenance; overall_status: OverallStatus; analysis_status: 'SUCCEEDED' | 'PARTIAL';
  analysis_scope?: { analysis_run_id: string; notice_facts: { code: string; message: string; evidence: Evidence[] }[]; dropped_requirements: { raw: string; reason_code: string }[]; pipeline_diagnostics: { code: string; message: string }[] } | null;
  judgment_counts: Record<JudgmentStatus, number>; judgments: (Judgment & { type: RequirementType; raw: string })[];
};
export type RequirementEvidenceResult = {
  provenance: ProductProvenance; requirement: QualificationRequirement; evidence: Evidence[];
};
export type RequiredChecksResult = {
  provenance: ProductProvenance; questions: QualificationQuestion[]; user_answer_requires_askable: true;
};
export type JudgmentProfileResult = {
  provenance: ProductProvenance; profile_snapshot: Record<string, unknown>; profile_completeness: ProfileCompleteness;
};
export type ProductSource = { source_origin: 'PRODUCT_EVIDENCE'; ref: string; evidence: Evidence };
export type DocumentSource = {
  source_origin: 'DOCUMENT_RAG'; ref: string; document_id: string; document_name: string;
  notice_version_id: string; chunk_id: string; clause_label: string | null; page: number | null;
  source_locations: string[]; quote: string;
};
export type CopilotSource = ProductSource | DocumentSource;
export type ActionInput = {
  satisfies_requirement: boolean; normalized_value?: string | null; evidence_held?: boolean; apply_to_profile?: false;
};
export type VersionState = {
  notice_version_id: string; version_number: number; analysis_run_id: string;
  analysis_status: 'SUCCEEDED' | 'PARTIAL'; judgment_run_id: string | null;
};
export type RevalidationProvenance = {
  case_id: string; notice_id: string; company_id: string; baseline: VersionState; current: VersionState; rule_version: string;
};
export type AnswerProposal = {
  action_type: 'ANSWER_REQUIREMENT'; expected: ProductProvenance; requirement_key: string;
  user_input: Required<ActionInput>; title: string; consequences: string;
};
export type RevalidationProposal = {
  action_type: 'REVALIDATE'; expected: RevalidationProvenance; title: string; consequences: string;
};
export type ActionProposal = AnswerProposal | RevalidationProposal;
export type ConfirmAction = { confirmed: true; action: ActionProposal };
export type RequirementChange = {
  change_type: 'UNCHANGED' | 'MODIFIED' | 'ADDED' | 'REMOVED'; identity: string;
  baseline_key: string | null; current_key: string | null;
  baseline: QualificationRequirement | null; current: QualificationRequirement | null;
};
export type ChangedNoticeResult = { provenance: RevalidationProvenance; changes: RequirementChange[] };
export type CopilotChatRequest = {
  response_version?: 'legacy' | '3.1'; conversation_id?: string; context_revision?: number; target_id?: string;
  job_id?: string; question_id?: string;
  case_id: string; message: string; requirement_key?: string | null; intent?: CopilotIntent | null;
  user_input?: ActionInput | null;
  conversation_context?: ConversationContext;
  /** Only this separate public question is eligible for external embedding, with explicit opt-in. */
  public_document_question?: string | null;
  allow_external_processing?: boolean;
};

export type GuidedQuestion = {
  question_id: string; label: string; order: number; answer_scope: string;
  completion_criteria: string[]; required_tools: string[];
  availability: 'AVAILABLE' | 'BLOCKED'; unavailable_reason: string | null;
};
export type GuidedJob = { job_id: string; label: string; order: number; questions: GuidedQuestion[] };
export type GuidedJobCatalog = { contract_version: 'copilot-guided-jobs-v1'; jobs: GuidedJob[] };
export type CopilotChatResponse = {
  envelope?: CopilotEnvelope | null;
  answer: string; intent: CopilotIntent;
  presentation?: Presentation | null; reply_context?: ReplyContext | null;
  // Backend has no discriminator on product_state; narrow by field presence, not intent alone.
  product_state: QualificationSummary | RequirementEvidenceResult | RequiredChecksResult | JudgmentProfileResult | ChangedNoticeResult | null;
  citations: CopilotSource[]; sources: CopilotSource[]; actions: ActionProposal[]; warnings: string[];
  external_processing_used: boolean; external_processing_scope: 'PUBLIC_NOTICE_DOCUMENT' | null;
};
export type JudgmentRun = {
  id: string; preflight_case_id: string; analysis_run_id: string; company_id: string; notice_version_id: string;
  overall_status: OverallStatus; rule_version: string; reference_date: string; analysis_status: string;
  profile_completeness: ProfileCompleteness; profile_snapshot: Record<string, unknown>; judgments: Judgment[]; created_at: string;
};
export type AnswerResult = {
  id: string; preflight_case_id: string; source_judgment_run_id: string; result_judgment_run_id: string;
  requirement_key: string; answer: Record<string, unknown>; normalized_value: string | null;
  evidence_held: boolean; apply_to_profile: boolean; created_at: string; result: JudgmentRun;
};
export type RevalidationResult = {
  id: string; preflight_case_id: string; source_judgment_run_id: string; result_judgment_run_id: string;
  baseline_analysis_run_id: string; current_analysis_run_id: string; changes: RequirementChange[];
  revalidated_keys: string[]; created_at: string; result: JudgmentRun;
};
export type ConfirmActionResult = AnswerResult | RevalidationResult;

async function post<T>(path: string, payload: CopilotChatRequest | ConfirmAction, signal?: AbortSignal): Promise<T> {
  const response = await apiFetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal,
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `요청에 실패했습니다. (${response.status})`,
      response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<T>;
}

export function sendCopilotMessage(payload: CopilotChatRequest, signal?: AbortSignal) {
  return post<CopilotChatResponse>('/api/v1/copilot/chat', payload, signal);
}

export async function getCopilotJobs(caseId: string, signal?: AbortSignal) {
  const response = await apiFetch(`/api/v1/copilot/jobs?case_id=${encodeURIComponent(caseId)}`, { signal });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(payload?.error?.message ?? `질문 목록을 불러오지 못했습니다. (${response.status})`,
      response.status, payload?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<GuidedJobCatalog>;
}

/** Invoke only after explicit confirmation. Pass the server proposal unchanged; never auto-retry. */
export function confirmCopilotAction(payload: ConfirmAction, signal?: AbortSignal) {
  return post<ConfirmActionResult>('/api/v1/copilot/actions/confirm', payload, signal);
}

export type ReadReceipt = { kind: 'product'; provenance: ProductProvenance } | { kind: 'revalidation'; provenance: RevalidationProvenance };
export type ConversationContext = {
  request_id?: string; context_revision: number; source_page?: 'QUALIFICATION' | 'ASK_BACK' | 'EVIDENCE' | 'CHANGES';
  last_response_intent?: string; visible_requirement_keys: string[]; last_read_receipt?: ReadReceipt | null;
};
export type ReplyContext = {
  request_id: string | null; context_revision: number; status: 'RESOLVED' | 'NEEDS_CONTEXT' | 'NEEDS_TARGET' | 'STALE_CONTEXT' | 'UNSUPPORTED';
  requirement_key: string | null; visible_requirement_keys: string[]; last_read_receipt: ReadReceipt | null;
};
export type Presentation = {
  conclusion: string; reasons: { text: string; requirement_key: string | null; evidence_refs: string[]; reason_code?: string | null; basis_type?: string | null }[];
  limitations: string[]; next_action: { kind: string; label: string; requirement_key: string | null } | null;
};
