import test from 'node:test';
import assert from 'node:assert/strict';
import { isRecommendationResponse, usesTrainedModel, safeRecommendationEvidenceHref, type MlRecommendationResponse } from './ml-recommendation-schema.ts';

const valid: MlRecommendationResponse = {
  model_version: 'lightgbm-abcdef', dataset_version: 'human-review-v1',
  scoring_source: 'local_lightgbm', input_sha256: 'hash', fallback_reason: null,
  fallback_used: false, total_valid_candidates: 1,
  note: 'Relevance only',
  items: [{
    notice_id: 'notice-1', title: '샘플 공고', rank: 1, relevance_score: 0.88,
    reason: 'Text relevance', version_number: 1,
    analysis_run_id: null, analysis_version: null, analysis_status: 'UNKNOWN',
    qualification_state: 'eligible', qualification_reason: null, rule_version: null, is_stale: false,
    deadline_source: 'explicit', effective_deadline: '2026-10-10T00:00:00Z',
  }],
  needs_review_items: [],
};

void test('POST recommendation contract matches account 4 schema', () => {
  assert.equal(isRecommendationResponse(valid), true);
  assert.equal(isRecommendationResponse({ ...valid, items: [{ ...valid.items[0], rank: 0 }] }), false);
  assert.equal(isRecommendationResponse({ ...valid, items: [{ ...valid.items[0], qualification_state: 'approved' }] }), false);
  assert.equal(isRecommendationResponse({ company_id: 'company-a', items: [] }), false);
  assert.equal(isRecommendationResponse({ ...valid, items: [{ ...valid.items[0], relevance_score: Number.NaN }] }), false);
  // Raw ranking scores aren't necessarily probabilities or clamped to [0,1].
  assert.equal(isRecommendationResponse({ ...valid, items: [{ ...valid.items[0], relevance_score: 1.25 }] }), true);
  assert.equal(isRecommendationResponse({ ...valid, needs_review_items: [{ ...valid.items[0], qualification_state: 'UNKNOWN' }] }), true);
  assert.equal(isRecommendationResponse({ ...valid, items: [{ ...valid.items[0], qualification_state: 'UNKNOWN' }] }), false);
  assert.equal(isRecommendationResponse({ ...valid, needs_review_items: [{ ...valid.items[0], qualification_state: 'eligible' }] }), false);
  assert.equal(isRecommendationResponse({ ...valid, needs_review_items: undefined }), false);
});

void test('lexical fallback is never represented as trained ML', () => {
  assert.equal(usesTrainedModel(valid), true);
  assert.equal(usesTrainedModel({ ...valid, scoring_source: 'lexical_fallback', model_version: null }), false);
  assert.equal(usesTrainedModel({ ...valid, scoring_source: 'remote_inference', model_version: null }), false);
});

void test('citations reject external and unsafe URLs', () => {
  assert.equal(safeRecommendationEvidenceHref('/api/v1/notices/a/documents/b/text'), '/api/v1/notices/a/documents/b/text');
  assert.equal(safeRecommendationEvidenceHref('https://evil.example'), null);
  assert.equal(safeRecommendationEvidenceHref('//evil.example'), null);
  assert.equal(safeRecommendationEvidenceHref('/api/v1/../evil//path'), null);
});
