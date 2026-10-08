import assert from 'node:assert/strict';
import test from 'node:test';

import { NOTICE_PAGE_SIZE, noticeListParams, noticePageRange } from './notice-pagination.ts';

void test('request includes only requested page, query, and business type', () => {
  const params = noticeListParams('  test  ', { limit: NOTICE_PAGE_SIZE, offset: 100, businessType: 'GOODS' });
  assert.equal(params.get('q'), 'test');
  assert.equal(params.get('business_type'), 'GOODS');
  assert.equal(params.get('offset'), '100');
  assert.equal(params.get('limit'), String(NOTICE_PAGE_SIZE));
  assert.equal(noticeListParams(' ', { businessType: 'all' }).get('limit'), '100');
  assert.equal(noticeListParams(' ', { businessType: 'all' }).has('business_type'), false);
  assert.equal(noticeListParams(' ', { businessType: 'all' }).has('q'), false);
});

void test('0, 10, 100, 101 and many results have correct page boundaries', () => {
  for (const [total, lastPage, lastSize] of [
    [0, 0, 0], [10, 0, 10], [100, 9, 10], [101, 10, 1], [1001, 100, 1],
  ]) {
    const info = noticePageRange(total, lastPage);
    assert.equal(info.end - info.start + (total === 0 ? 0 : 1), lastSize);
    assert.equal(info.hasNext, false);
    assert.equal(info.hasPrevious, lastPage > 0);
  }
});

void test('all offsets traverse 101 results exactly once, including the 101st', () => {
  const ids = Array.from({ length: 101 }, (_, index) => 'notice-' + (index + 1));
  const visited: string[] = [];
  for (let page = 0; page < noticePageRange(ids.length, 0).pageCount; page += 1) {
    const params = noticeListParams('urgent', { limit: NOTICE_PAGE_SIZE, offset: page * NOTICE_PAGE_SIZE, businessType: 'FOREIGN' });
    const offset = Number(params.get('offset'));
    visited.push(...ids.slice(offset, offset + Number(params.get('limit'))));
  }
  assert.deepEqual(visited, ids);
  assert.equal(new Set(visited).size, 101);
});

void test('filter and query changes restart at offset zero', () => {
  assert.equal(noticeListParams('new query', { offset: 0, businessType: 'SERVICE' }).get('offset'), '0');
  assert.equal(noticeListParams('new query', { offset: 0, businessType: 'SERVICE' }).get('q'), 'new query');
  assert.deepEqual(noticePageRange(14, 1), {
    start: 11, end: 14, pageCount: 2, hasPrevious: true, hasNext: false,
  });
});
