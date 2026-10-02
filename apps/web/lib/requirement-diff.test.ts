import assert from 'node:assert/strict';
import test from 'node:test';

import type { CanonicalRequirement } from './qualification-api.ts';
import { diffCanonicalRequirements, sameStructuredRequirement } from './requirement-diff.ts';

function requirement(overrides: Partial<CanonicalRequirement> = {}): CanonicalRequirement {
  return {
    requirement_key: 'REQ-INDUSTRY',
    requirement_group_key: null,
    group_operator: null,
    notice_version_id: 'version',
    type: 'INDUSTRY',
    operator: 'EQ',
    value: '1224',
    unit: null,
    period_months: null,
    scope: {},
    requirement_role: 'ELIGIBILITY',
    condition_complexity: 'SIMPLE',
    required: true,
    raw: '업종코드 1224',
    evidence_keys: ['EVD-1'],
    ...overrides,
  };
}

void test('업종 값 1224에서 1227로 바뀌면 MODIFIED다', () => {
  const before = requirement();
  const after = requirement({ value: '1227', raw: '업종코드 1227' });
  const [change] = diffCanonicalRequirements([before], [after]);

  assert.equal(change.change_type, 'MODIFIED');
  assert.equal(sameStructuredRequirement(before, after), false);
});

void test('표시 값이 같아도 operator만 바뀌면 구조화 변경이다', () => {
  const before = requirement({ value: 5, operator: 'GTE', raw: '실적 5' });
  const after = requirement({ value: 5, operator: 'GT', raw: '실적 5' });
  const [change] = diffCanonicalRequirements([before], [after]);

  assert.equal(change.change_type, 'MODIFIED');
  assert.equal(sameStructuredRequirement(before, after), false);
});

void test('표시 값이 같아도 scope만 바뀌면 구조화 변경이다', () => {
  const before = requirement({ scope: { region: '전북특별자치도' } });
  const after = requirement({ scope: { region: '광주광역시' } });
  const [change] = diffCanonicalRequirements([before], [after]);

  assert.equal(change.change_type, 'MODIFIED');
  assert.equal(sameStructuredRequirement(before, after), false);
});
