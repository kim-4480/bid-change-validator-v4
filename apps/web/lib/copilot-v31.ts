import type { ActionProposal, ProductProvenance } from './copilot-api';

export type CopilotEnvelope = {
  version: '3.1'; conversation_id: string; context_revision: number; message_id: string;
  status_card: { status: string; text: string; provenance: ProductProvenance } | null;
  claims: { claim_id: string; text: string; fact_ids: string[]; source_ids: string[];
    validation: 'SUPPORTED'; method: 'rule' | 'extractive' | 'semantic'; reason: string }[];
  sources: { source_id: string; kind: 'DOCUMENT' | 'PRODUCT' | 'TURN'; quote: string;
    document_id: string | null; location: Record<string, unknown>;
    scope: { case_id: string; company_id: string | null; notice_version_id: string } }[];
  follow_up_targets: { target_id: string; kind: string; label: string; message_id: string;
    ordinal: number; fact_ids: string[]; source_ids: string[]; requirement_key: string | null }[];
  capabilities: Record<string, number>; actions: ActionProposal[];
  limitations: string[]; clarification: string | null;
  guided: { job_id: string; question_id: string; status: 'COMPLETE' | 'PARTIAL' | 'BLOCKED'; next_question_id: string | null } | null;
  processing: { path: 'v3.1'; model: string | null; fallback: boolean; task_status: 'PASS' | 'PARTIAL' | 'FAIL'; elapsed_ms: number;
    validation_events?: { stage?: string; reason?: string; budget_code?: string }[]; tools?: { tool?: string; coverage?: string }[] };
};

export function copilotFailureMessage(envelope: CopilotEnvelope): string | null {
  if (envelope.processing.task_status !== 'FAIL' || envelope.claims.length) return null;
  if (envelope.processing.validation_events?.some(event => event.budget_code === 'INPUT_BUDGET')) {
    return '공고문 근거가 너무 많아 답변을 생성하지 못했습니다. 질문 범위를 좁혀 다시 시도해 주세요.';
  }
  if (envelope.processing.tools?.some(tool => tool.coverage === 'UNAVAILABLE' &&
      (tool.tool === 'READ_JUDGMENT' || tool.tool === 'READ_CHANGES'))) {
    return '현재 기준의 분석·판정 자료를 확인하지 못해 답변을 생성하지 않았습니다. 참가자격 화면에서 분석 상태를 확인해 주세요.';
  }
  if (envelope.processing.tools?.some(tool => tool.tool === 'READ_DOCUMENT' && tool.coverage === 'UNAVAILABLE')) {
    return '현재 공고문 근거를 확인하지 못했습니다. 원문 화면에서 문서 상태를 확인해 주세요.';
  }
  if (envelope.processing.validation_events?.some(event => event.reason === 'BudgetExceeded')) {
    return 'AI 처리 시간이나 호출 한도에 도달했습니다. 잠시 후 다시 시도해 주세요.';
  }
  return '검증된 답변을 만들지 못했습니다. 원문과 판정 상태를 확인한 뒤 다시 시도해 주세요.';
}

export function validateEnvelope(envelope: CopilotEnvelope, caseId?: string) {
  const sources = new Map(envelope.sources.map(source => [source.source_id, source]));
  if (sources.size !== envelope.sources.length || envelope.claims.some(claim =>
    claim.validation !== 'SUPPORTED' || !claim.source_ids.length || claim.source_ids.some(id => !sources.get(id)?.quote.trim())) ||
    envelope.sources.some(source => caseId && source.scope.case_id !== caseId) ||
    envelope.follow_up_targets.some(target => target.message_id !== envelope.message_id ||
      target.source_ids.some(id => !sources.has(id)))) {
    throw new Error('답변의 문장별 근거 연결을 확인하지 못했습니다. 다시 조회해 주세요.');
  }
}
