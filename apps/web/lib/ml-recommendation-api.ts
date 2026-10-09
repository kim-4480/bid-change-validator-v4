import { apiFetch, ApiError } from './api';
import { isRecommendationResponse, type MlRecommendationResponse } from './ml-recommendation-schema';
export { usesTrainedModel } from './ml-recommendation-schema';
export type { MlRecommendation, MlRecommendationResponse } from './ml-recommendation-schema';

const EXPECTED_PATH = '/api/v1/recommendations/ml';

/** Explicit opt-in until the ML router is mounted and deployed by the backend owner. */
export function mlEndpointConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_ML_RECOMMENDATIONS_PATH);
}

export function mlRecommendationEndpoint(): string | null {
  const configured = process.env.NEXT_PUBLIC_ML_RECOMMENDATIONS_PATH;
  if (!configured) return null;
  // Do not allow redirects to external servers or ad-hoc API paths.
  if (configured !== EXPECTED_PATH) throw new Error('추천 API 경로 계약이 올바르지 않습니다.');
  return configured;
}

export async function listMlRecommendations(companyId: string): Promise<MlRecommendationResponse | null> {
  const endpoint = mlRecommendationEndpoint();
  if (!endpoint) return null;
  const response = await apiFetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ company_id: companyId, limit: 50 }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string; error?: { message?: string } } | null;
    throw new ApiError(
      payload?.error?.message ?? payload?.detail ?? '추천 API 응답을 받지 못했습니다. (' + response.status + ')',
      response.status,
      'ML_API_ERROR',
    );
  }
  const result: unknown = await response.json();
  if (!isRecommendationResponse(result)) throw new Error('추천 API 응답 형식이 Backend 계약과 일치하지 않습니다.');
  return result;
}
