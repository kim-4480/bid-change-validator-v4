import { apiFetch, ApiError } from './api';
import { isRecommendationResponse, type MlRecommendationResponse } from './ml-recommendation-schema';
export { usesTrainedModel } from './ml-recommendation-schema';
export type { MlRecommendation, MlRecommendationResponse } from './ml-recommendation-schema';

const EXPECTED_PATH = '/api/v1/recommendations/ml';

export function mlRecommendationEndpoint(): string {
  return EXPECTED_PATH;
}

export async function listMlRecommendations(companyId: string): Promise<MlRecommendationResponse> {
  const endpoint = mlRecommendationEndpoint();
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
