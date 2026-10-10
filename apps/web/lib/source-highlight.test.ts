import assert from 'node:assert/strict';
import { test } from 'node:test';

import { highlightCounts, highlightSegments } from './source-highlight.ts';

const DOC = `4. 입찰참가자격
가. 본점 소재지가 강릉시에 있는 업체
나. 「소방시설공사업법」에 의한 【전문소방시설공사업】
    면허를 보유한 업체
다. 공동수급 불가`;

void test('띄어쓰기·줄바꿈이 달라도 조항을 찾아 칠한다', () => {
  const segments = highlightSegments(DOC, [
    { text: '나. 「소방시설공사업법」에 의한【전문소방시설공사업】 면허를 보유한 업체', kind: 'VERDICT', label: '업종 · 0040' },
  ]);
  const marked = segments.filter((item) => item.kind === 'VERDICT').map((item) => item.text).join('');
  assert.ok(marked.startsWith('나. 「소방시설공사업법」'));
  assert.ok(marked.endsWith('면허를 보유한 업체'));
  assert.equal(segments.map((item) => item.text).join(''), DOC); // 원문은 그대로 다시 이어진다
});

void test('겹치면 우선순위가 높은 종류가 이긴다', () => {
  const segments = highlightSegments(DOC, [
    { text: '가. 본점 소재지가 강릉시에 있는 업체', kind: 'GAP_CHECKLIST', label: '미정리' },
    { text: '본점 소재지가 강릉시에 있는 업체', kind: 'VERDICT', label: '지역 · 강릉시' },
  ]);
  assert.equal(segments.find((item) => item.text.includes('강릉시'))?.kind, 'VERDICT');
  assert.deepEqual(highlightCounts(segments).VERDICT, 1);
});

void test('통째로 없으면 앞부분이 맞는 만큼만 칠한다', () => {
  const segments = highlightSegments(DOC, [
    { text: '다. 공동수급 불가 (단, 하도급은 허용)', kind: 'NOTE', label: '참고 정보' },
  ]);
  assert.equal(segments.filter((item) => item.kind === 'NOTE').map((item) => item.text).join(''), '다. 공동수급 불가');
});

void test('너무 짧은 조각은 칠하지 않는다', () => {
  const segments = highlightSegments(DOC, [{ text: '업체', kind: 'CHECKLIST', label: 'x' }]);
  assert.ok(segments.every((item) => item.kind === null));
});
