import { apiFetch, ApiError } from './api';
import { isRecommendationResponse, type MlRecommendationResponse } from './ml-recommendation-schema';
export { safeRecommendationEvidenceHref } from './ml-recommendation-schema';
export type { MlRecommendation, MlRecommendationResponse } from './ml-recommendation-schema';

/**
 * A backend contract is still being finalized by the ML owner.
 * The URL is intentionally unconfigured in production until that contract is approved.
 * Only an authenticated same-origin /api/v1/ route is allowed.
 */
export function mlEndpointConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_ML_RECOMMENDATIONS_PATH);
}

export async function listMlRecommendations(companyId: string): Promise<MlRecommendationResponse | null> {
  const endpoint = process.env.NEXT_PUBLIC_ML_RECOMMENDATIONS_PATH;
  if (!endpoint) return null;
  if (!/^\/api\/v1\/[a-z0-9_/-]+$/i.test(endpoint)) {
    throw new Error('추천 API 경로 설정이 올바르지 않습니다.');
  }
  const response = await apiFetch(endpoint + '?company_id=' + encodeURIComponent(companyId));
  if (!response.ok) {
    throw new ApiError('추천 API 응답을 받지 못했습니다. (' + response.status + ')', response.status, 'ML_API_ERROR');
  }
  const result: unknown = await response.json();
  if (!isRecommendationResponse(result, companyId)) {
    throw new Error('추천 API의 응답 계약이 일치하지 않습니다.');
  }
  return result;
}
