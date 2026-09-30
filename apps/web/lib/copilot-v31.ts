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
  processing: { path: 'v3.1'; model: string | null; fallback: boolean; task_status: 'PASS' | 'PARTIAL' | 'FAIL'; elapsed_ms: number };
};

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
