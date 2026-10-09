/** Mirrors account 4's POST /api/v1/recommendations/ml Pydantic response.
 * Recommendation score is a rank signal, NOT a calibrated probability.
 */
export type MlScoringSource = 'local_lightgbm' | 'local_hf' | 'remote_inference' | 'lexical_fallback';
export type MlQualificationState = 'eligible' | 'ineligible' | 'insufficient_data' | 'UNKNOWN' | 'stale';

export type MlRecommendation = {
  notice_id: string;
  title: string;
  rank: number;
  relevance_score: number;
  reason: string;
  version_number: number;
  analysis_run_id: string | null;
  analysis_version: string | null;
  analysis_status: string;
  qualification_state: MlQualificationState;
  qualification_reason: string | null;
  rule_version: string | null;
  is_stale: boolean;
};

export type MlRecommendationResponse = {
  model_version: string | null;
  dataset_version: string | null;
  scoring_source: MlScoringSource;
  input_sha256: string | null;
  fallback_reason: string | null;
  note: string;
  items: MlRecommendation[];
};

const SOURCES = new Set<MlScoringSource>(['local_lightgbm', 'local_hf', 'remote_inference', 'lexical_fallback']);
const STATES = new Set<MlQualificationState>(['eligible', 'ineligible', 'insufficient_data', 'UNKNOWN', 'stale']);
const nullableString = (value: unknown) => value === null || typeof value === 'string';

export function isRecommendationResponse(value: unknown): value is MlRecommendationResponse {
  if (!value || typeof value !== 'object') return false;
  const result = value as Record<string, unknown>;
  if (!SOURCES.has(result.scoring_source as MlScoringSource)
    || !nullableString(result.model_version) || !nullableString(result.dataset_version)
    || !nullableString(result.input_sha256) || !nullableString(result.fallback_reason)
    || typeof result.note !== 'string' || !Array.isArray(result.items)) return false;
  return result.items.every((item: unknown) => {
    if (!item || typeof item !== 'object') return false;
    const row = item as Record<string, unknown>;
    return typeof row.notice_id === 'string' && row.notice_id.length > 0
      && typeof row.title === 'string' && typeof row.reason === 'string'
      && Number.isInteger(row.rank) && (row.rank as number) > 0
      && typeof row.relevance_score === 'number' && Number.isFinite(row.relevance_score)
      && Number.isInteger(row.version_number) && (row.version_number as number) > 0
      && nullableString(row.analysis_run_id) && nullableString(row.analysis_version)
      && typeof row.analysis_status === 'string'
      && STATES.has(row.qualification_state as MlQualificationState)
      && nullableString(row.qualification_reason) && nullableString(row.rule_version)
      && typeof row.is_stale === 'boolean';
  });
}

/** Fallback or missing model metadata must never be labeled as trained ML. */
export function usesTrainedModel(response: MlRecommendationResponse): boolean {
  return response.scoring_source !== 'lexical_fallback'
    && typeof response.model_version === 'string' && response.model_version.trim().length > 0;
}

/** Allow only authenticated backend-relative citations, never arbitrary URLs. */
export function safeRecommendationEvidenceHref(value: string | null | undefined): string | null {
  return value?.startsWith('/api/v1/') && !value.includes('//') && !value.includes('\\')
    && !value.split('/').includes('..') ? value : null;
}
