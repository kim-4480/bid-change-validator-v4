export type MlRecommendation = {
  notice_id: string;
  bid_notice_no: string;
  title: string;
  rank: number;
  relevance_score: number;
  model_version: string;
  reasons: string[];
  evidence_href?: string | null;
};

export type MlRecommendationResponse = {
  company_id: string;
  items: MlRecommendation[];
};

export function isRecommendationResponse(value: unknown, companyId: string): value is MlRecommendationResponse {
  if (!value || typeof value !== 'object') return false;
  const result = value as Record<string, unknown>;
  if (result.company_id !== companyId || !Array.isArray(result.items)) return false;
  return result.items.every((item: unknown) => {
    if (!item || typeof item !== 'object') return false;
    const row = item as Record<string, unknown>;
    return typeof row.notice_id === 'string' && typeof row.bid_notice_no === 'string'
      && typeof row.title === 'string' && typeof row.model_version === 'string'
      && typeof row.rank === 'number' && Number.isInteger(row.rank) && row.rank > 0
      && typeof row.relevance_score === 'number' && Number.isFinite(row.relevance_score)
      && row.relevance_score >= 0 && row.relevance_score <= 1
      && Array.isArray(row.reasons) && row.reasons.every((reason: unknown) => typeof reason === 'string')
      && (row.evidence_href == null || typeof row.evidence_href === 'string');
  });
}

export function safeRecommendationEvidenceHref(value: string | null | undefined): string | null {
  return value?.startsWith('/api/v1/') && !value.includes('//') && !value.includes('\\') && !value.split('/').includes('..') ? value : null;
}