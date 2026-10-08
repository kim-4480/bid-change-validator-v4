import test from 'node:test';
import assert from 'node:assert/strict';
import { isRecommendationResponse, safeRecommendationEvidenceHref } from './ml-recommendation-schema.ts';

const valid = {
  company_id: 'company-a',
  items: [{ notice_id: 'notice-1', bid_notice_no: '2026-0001', title: '샘플 공고',
    rank: 1, relevance_score: 0.88, model_version: 'local-test-v1',
    reasons: ['업종 연관성'], evidence_href: '/api/v1/notices/notice-1/versions/1/documents/id/text' }],
};

void test('ML result must match the requested company snapshot and bounded score', () => {
  assert.equal(isRecommendationResponse(valid, 'company-a'), true);
  assert.equal(isRecommendationResponse(valid, 'company-b'), false);
  assert.equal(isRecommendationResponse({ ...valid, items: [{ ...valid.items[0], relevance_score: 120 }] }, 'company-a'), false);
});

void test('citation URLs may only open authenticated backend document routes', () => {
  assert.equal(safeRecommendationEvidenceHref(valid.items[0].evidence_href), valid.items[0].evidence_href);
  assert.equal(safeRecommendationEvidenceHref('https://evil.example/steal'), null);
  assert.equal(safeRecommendationEvidenceHref('//evil.example'), null);
  assert.equal(safeRecommendationEvidenceHref('/api/v1/../evil//path'), null);
});