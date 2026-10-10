import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createQueryClient, mayCacheGet, queryKeyForGet, STALE_MS } from './shared-query-cache.ts';

void test('only explicitly safe list endpoints are cacheable', () => {
  assert.equal(mayCacheGet('/api/v1/companies'), true);
  assert.equal(mayCacheGet('/api/v1/notices?limit=10&offset=0'), true);
  assert.equal(mayCacheGet('/api/v1/preflight-cases?limit=100'), true);
  assert.equal(mayCacheGet('/api/v1/master-codes/industries?limit=20'), true);
  assert.equal(mayCacheGet('/api/v1/notices/uuid'), true);
  assert.equal(mayCacheGet('/api/v1/notices/uuid/versions'), true);
  assert.equal(mayCacheGet('/api/v1/preflight-cases/uuid'), true);
  assert.equal(mayCacheGet('/api/v1/qualification-judgment-runs/uuid'), true);
  assert.equal(mayCacheGet('/api/v1/qualification-analyses/uuid'), false);
  assert.equal(mayCacheGet('/api/v1/preflight-cases/uuid/qualification-judgment-runs'), false);
  assert.equal(mayCacheGet('/api/v1/admin/processing-jobs'), false);
  assert.equal(mayCacheGet('/api/v1/auth/me'), false);
});
void test('query key isolates company, page, query, and qualification filter', () => {
  const a = queryKeyForGet('/api/v1/notices?company_id=a&offset=0');
  const b = queryKeyForGet('/api/v1/notices?company_id=b&offset=0');
  const c = queryKeyForGet('/api/v1/notices?company_id=a&offset=10');
  assert.notDeepEqual(a, b);
  assert.notDeepEqual(a, c);
});
void test('query client deduplicates GET, retains data, and invalidates on demand', async () => {
  const client = createQueryClient();
  let calls = 0;
  const fetchList = () => client.fetchQuery({
    queryKey: queryKeyForGet('/api/v1/companies'),
    queryFn: async () => { calls++; return [{ id: 'a' }]; },
  });
  const [first, second] = await Promise.all([fetchList(), fetchList()]);
  assert.deepEqual(first, second);
  await fetchList();
  assert.equal(calls, 1);
  assert.equal(client.getQueryData(queryKeyForGet('/api/v1/companies')), first);
  await client.invalidateQueries({ queryKey: queryKeyForGet('/api/v1/companies') });
  await fetchList();
  assert.equal(calls, 2);
  assert.equal(client.getDefaultOptions().queries?.staleTime, STALE_MS);
  client.clear();
});
