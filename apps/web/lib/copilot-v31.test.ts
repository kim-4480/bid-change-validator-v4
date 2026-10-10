import assert from 'node:assert/strict';
import test from 'node:test';
import { copilotFailureMessage, type CopilotEnvelope } from './copilot-v31.ts';

function result(processing: Partial<CopilotEnvelope['processing']>, claims: CopilotEnvelope['claims'] = []) {
  return { claims, processing: { task_status: 'FAIL', ...processing } } as CopilotEnvelope;
}

void test('document budget failures show an actionable message', () => {
  assert.match(copilotFailureMessage(result({ validation_events: [{ stage: 'generate', reason: 'BudgetExceeded', budget_code: 'INPUT_BUDGET' }] })) ?? '', /질문 범위를 좁혀/);
});

void test('unavailable current analysis is not displayed as an answer', () => {
  assert.match(copilotFailureMessage(result({ tools: [{ tool: 'READ_JUDGMENT', coverage: 'UNAVAILABLE' }] })) ?? '', /분석·판정/);
});

void test('partial or grounded replies do not show a failure warning', () => {
  assert.equal(copilotFailureMessage(result({ task_status: 'PARTIAL' })), null);
  assert.equal(copilotFailureMessage(result({}, [{ claim_id: 'c1' } as CopilotEnvelope['claims'][number]])), null);
});
