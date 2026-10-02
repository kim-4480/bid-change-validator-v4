/** Synthetic UI fixtures only. Never submit their IDs or proposals to a real case. */
import type { CopilotChatResponse, DocumentSource, ProductProvenance, ProductSource,
  QualificationRequirement, QualificationSummary, RevalidationProvenance } from './copilot-api';

const provenance = {
  case_id: '00000000-0000-4000-8000-000000000001', notice_id: '00000000-0000-4000-8000-000000000002',
  notice_version_id: '00000000-0000-4000-8000-000000000003', version_number: 2,
  company_id: '00000000-0000-4000-8000-000000000004', analysis_run_id: '00000000-0000-4000-8000-000000000005',
  judgment_run_id: '00000000-0000-4000-8000-000000000006', analysis_status: 'SUCCEEDED', rule_version: 'qualification-rules-v0.2',
} satisfies ProductProvenance;
const requirement = {
  requirement_key: 'REQ-REGISTRATION', requirement_group_key: null, group_operator: null,
  notice_version_id: provenance.notice_version_id, type: 'REGISTRATION_CERTIFICATION', operator: 'MATCH',
  value: '정보통신공사업', unit: null, period_months: null, scope: {}, required: true,
  requirement_role: 'mandatory', condition_complexity: 'simple',
  raw: '정보통신공사업 등록업체이어야 한다.', confidence: 1, evidence_keys: ['E1'],
} satisfies QualificationRequirement;
const summary = {
  provenance, overall_status: 'insufficient_data', analysis_status: 'SUCCEEDED',
  judgment_counts: { SATISFIED: 0, UNSATISFIED: 0, UNKNOWN: 1 },
  judgments: [{ judgment_key: 'J1', preflight_case_id: provenance.case_id, notice_version_id: provenance.notice_version_id,
    requirement_key: requirement.requirement_key, status: 'UNKNOWN', basis_type: 'NONE', evidence_held: false,
    reason_code: 'INSUFFICIENT_DATA', requires_evidence: true, profile_refs: [], requirement_evidence_keys: ['E1'],
    rule_version: provenance.rule_version, type: requirement.type, raw: requirement.raw }],
} satisfies QualificationSummary;
const productSource = {
  source_origin: 'PRODUCT_EVIDENCE', ref: 'S1', evidence: {
    evidence_key: 'E1', source_type: 'NOTICE_DOCUMENT', document_id: '00000000-0000-4000-8000-000000000007',
    notice_version_id: provenance.notice_version_id, case_id: null, chunk_id: 'C1',
    location: { clause_label: '2', page: null, display: '섹션 1 문단 3', section_index: 1, paragraph_start: 3, paragraph_end: 3 },
    quote: requirement.raw, source_sha256: null, extracted_text_sha256: null,
  },
} satisfies ProductSource;
const documentSource = {
  source_origin: 'DOCUMENT_RAG', ref: 'S1', document_id: productSource.evidence.document_id,
  document_name: '예시 공고문.pdf', notice_version_id: provenance.notice_version_id,
  chunk_id: 'C1', clause_label: '2', page: null, source_locations: ['p.2', 'p.3'], quote: requirement.raw,
} satisfies DocumentSource;
const lineage = {
  case_id: provenance.case_id, notice_id: provenance.notice_id, company_id: provenance.company_id,
  baseline: { notice_version_id: '00000000-0000-4000-8000-000000000008', version_number: 1,
    analysis_run_id: '00000000-0000-4000-8000-000000000009', analysis_status: 'SUCCEEDED',
    judgment_run_id: '00000000-0000-4000-8000-000000000010' },
  current: { notice_version_id: provenance.notice_version_id, version_number: 2, analysis_run_id: provenance.analysis_run_id,
    analysis_status: 'SUCCEEDED', judgment_run_id: null }, rule_version: provenance.rule_version,
} satisfies RevalidationProvenance;
const empty = {
  answer: '', intent: 'UNKNOWN', product_state: null, citations: [], sources: [], actions: [], warnings: [],
  external_processing_used: false, external_processing_scope: null,
} satisfies CopilotChatResponse;
const question = {
  requirement_key: requirement.requirement_key, requirement_type: requirement.type,
  question: '정보통신공사업 등록을 보유하고 있나요?', raw_requirement: requirement.raw,
  askable: true, askability_reason_code: 'ASKABLE_SIMPLE_FACT', askability_reason: '등록 여부 확인',
};

export const copilotMocks = {
  eligible: { ...empty, intent: 'QUALIFICATION_SUMMARY', answer: '저장된 판정: 참가 가능 (분석 상태: SUCCEEDED).',
    product_state: { ...summary, overall_status: 'eligible', judgment_counts: { SATISFIED: 1, UNSATISFIED: 0, UNKNOWN: 0 },
      judgments: [{ ...summary.judgments[0], status: 'SATISFIED', basis_type: 'PROFILE', reason_code: 'RULE_MATCH' }] } },
  ineligible: { ...empty, intent: 'QUALIFICATION_SUMMARY', answer: '저장된 판정: 참가 불가 (분석 상태: SUCCEEDED).',
    product_state: { ...summary, overall_status: 'ineligible', judgment_counts: { SATISFIED: 0, UNSATISFIED: 1, UNKNOWN: 0 },
      judgments: [{ ...summary.judgments[0], status: 'UNSATISFIED', basis_type: 'PROFILE', reason_code: 'RULE_MISMATCH' }] } },
  insufficientData: { ...empty, intent: 'QUALIFICATION_SUMMARY', answer: '저장된 판정: 확인 필요 (분석 상태: SUCCEEDED).', product_state: summary },
  askableUnknown: { ...empty, intent: 'REQUIRED_CHECKS', answer: question.question,
    product_state: { provenance, questions: [question], user_answer_requires_askable: true } },
  nonAskableUnknown: { ...empty, intent: 'REQUIRED_CHECKS', answer: '사용자 답변만으로 판정할 수 없습니다. 원문을 확인해 주세요.',
    product_state: { provenance, user_answer_requires_askable: true, questions: [{ ...question, askable: false,
      question: '근거 원문을 직접 확인해 주세요.', raw_requirement: '공동수급체 구성원 모두 등록업체이어야 한다.',
      askability_reason_code: 'REQUIRES_SOURCE_REVIEW', askability_reason: '구성원별 조건 검토 필요' }] } },
  productEvidence: { ...empty, intent: 'REQUIREMENT_EVIDENCE', answer: `${requirement.raw} [S1]`,
    product_state: { provenance, requirement, evidence: [productSource.evidence] }, sources: [productSource], citations: [productSource] },
  documentRag: { ...empty, intent: 'DOCUMENT_QA', answer: '검색된 공고문 원문 1건입니다. [S1] 예시 공고문.pdf; clause=2; location=p.2, p.3',
    sources: [documentSource], citations: [documentSource], external_processing_used: true, external_processing_scope: 'PUBLIC_NOTICE_DOCUMENT',
    warnings: ['검색된 원문이며 참가자격 판정이 아닙니다.'] },
  answerProposal: { ...empty, intent: 'ACTION_REQUEST', answer: '답변 적용 제안입니다. 아직 저장하지 않았습니다.', actions: [{
    action_type: 'ANSWER_REQUIREMENT', expected: provenance, requirement_key: requirement.requirement_key,
    user_input: { satisfies_requirement: true, normalized_value: '정보통신공사업', evidence_held: true, apply_to_profile: false },
    title: '요건 답변 적용', consequences: '선택한 요건의 사용자 답변으로 새 판정을 저장합니다. 회사 프로필은 변경하지 않습니다.',
  }] },
  revalidationProposal: { ...empty, intent: 'CHANGED_NOTICE', answer: '변경 내역입니다. 재검증은 별도 확인 후 실행됩니다.',
    product_state: { provenance: lineage, changes: [] }, actions: [{ action_type: 'REVALIDATE', expected: lineage,
      title: '변경공고 재검증', consequences: '기준 판정에서 변경된 요건을 재검증하여 현재 버전의 새 판정을 저장합니다.' }] },
  consentRequired: { ...empty, intent: 'DOCUMENT_QA', answer: '공개 공고문 질문을 별도로 입력하고 외부 처리에 명시적으로 동의해 주세요.' },
  noEvidence: { ...empty, intent: 'DOCUMENT_QA', answer: '검색된 공고문 근거가 없습니다.',
    external_processing_used: true, external_processing_scope: 'PUBLIC_NOTICE_DOCUMENT' },
} satisfies Record<string, CopilotChatResponse>;

/** HTTP 409 error payload, deliberately separate from a successful chat response. */
export const staleActionErrorMock = {
  error: { code: 'STALE_ACTION_CONTEXT', message: '제안 이후 판정 문맥이 변경되었습니다.', details: null },
} satisfies { error: { code: string; message: string; details: unknown } };
