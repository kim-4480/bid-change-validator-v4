import type { ActionProposal, CopilotChatResponse, CopilotSource, OverallStatus } from './copilot-api';

export function getCopilotStatusLabel(status: OverallStatus): string {
  return { eligible: '참가 가능', ineligible: '참가 불가', insufficient_data: '확인 필요' }[status];
}

export function getCopilotActionLabel(action: ActionProposal): string {
  return action.title;
}

export function getSourceLabel(source: CopilotSource): string {
  return source.source_origin === 'PRODUCT_EVIDENCE' ? '공고 원문 근거' : '문서 검색 결과';
}

export function getSourceLocationLabel(source: CopilotSource): string {
  const product = source.source_origin === 'PRODUCT_EVIDENCE' ? source.evidence.location : null;
  const clause = product ? product.clause_label : source.source_origin === 'DOCUMENT_RAG' ? source.clause_label : null;
  const locations = source.source_origin === 'DOCUMENT_RAG' ? source.source_locations.filter(Boolean) : [];
  const page = product ? product.page : source.source_origin === 'DOCUMENT_RAG' ? source.page : null;
  const parts = [
    page != null ? `p.${page}` : '',
    product?.section_index != null ? `섹션 ${product.section_index}` : '',
    product?.paragraph_start != null ? `문단 ${product.paragraph_start}–${product.paragraph_end ?? product.paragraph_start}` : '',
    product?.block_start != null ? `블록 ${product.block_start}–${product.block_end ?? product.block_start}` : '',
    product?.source_line_start != null ? `줄 ${product.source_line_start}–${product.source_line_end ?? product.source_line_start}` : '',
  ].filter(Boolean);
  const location = locations.join(', ') || product?.display || parts.join(' · ');
  return [clause ? `조항 ${clause}` : '', location].filter(Boolean).join(' · ') || '위치 정보 없음';
}

export function getCopilotWarningItems(response: CopilotChatResponse): string[] {
  return [...response.warnings];
}
