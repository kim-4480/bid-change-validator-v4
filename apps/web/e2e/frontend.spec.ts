import { expect, test, type Page } from '@playwright/test';
import { NOTICE_PAGE_SIZE } from '../lib/notice-pagination';

const mockUser = {
  id: 'local-user', username: 'e2e-user', role: 'viewer',
  company_id: null, company_name: null,
};

type MockOptions = { authenticated?: boolean; noticesFail?: boolean };

async function mockApi(page: Page, options: MockOptions = {}) {
  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (pathname === '/api/v1/auth/me') {
      return route.fulfill(options.authenticated === false
        ? { status: 401, contentType: 'application/json', body: JSON.stringify({ error: { code: 'UNAUTHORIZED', message: '인증이 만료되었습니다.' } }) }
        : { status: 200, json: mockUser });
    }
    if (pathname === '/api/v1/auth/login') {
      return route.fulfill({ status: 401, json: { error: { code: 'INVALID_CREDENTIALS', message: '로그인 정보가 올바르지 않습니다.' } } });
    }
    if (pathname === '/api/v1/companies') {
      return route.fulfill({ status: 200, json: [] });
    }
    if (pathname === '/api/v1/notices') {
      if (options.noticesFail) {
        return route.fulfill({ status: 503, json: { error: { code: 'UPSTREAM_UNAVAILABLE', message: '일시적으로 공고를 조회할 수 없습니다.' } } });
      }
      const limit = Number(url.searchParams.get('limit') ?? 20);
      const offset = Number(url.searchParams.get('offset') ?? 0);
      const all = Array.from({ length: 101 }, (_, index) => ({
        id: 'notice-' + (index + 1),
        bid_notice_no: '2026-' + String(index + 1).padStart(4, '0'),
        title: '테스트 공고 ' + (index + 1),
        business_type: 'service',
        notice_kind: 'normal',
        announcing_institution_code: null,
        announcing_institution_name: '테스트 기관',
        demanding_institution_code: null,
        demanding_institution_name: null,
        first_seen_at: '2026-10-09T00:00:00',
        last_seen_at: '2026-10-09T00:00:00',
        current_version: 1,
        qualification_status: 'unreviewed',
        current_case_id: null,
      }));
      return route.fulfill({ status: 200, json: {
        total: all.length,
        items: all.slice(offset, offset + limit),
        status_counts: { eligible: 0, insufficient_data: 0, ineligible: 0, unreviewed: 101, needs_review: 0 },
      } });
    }
    // No request can escape to a real backend or an AWS endpoint during local E2E.
    return route.fulfill({ status: 404, json: { error: { message: 'Local fixture not defined' } } });
  });
}

test('login: hydration-safe form shows invalid credentials and never sends a GET password', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/login');
  const submit = page.getByRole('button', { name: '로그인' });
  await expect(submit).toBeEnabled({ timeout: 15_000 });
  await page.getByLabel('아이디').fill('invalid');
  await page.getByLabel('비밀번호').fill('invalid');
  const loginRequest = page.waitForRequest(request => request.url().includes('/api/v1/auth/login') && request.method() === 'POST');
  await submit.click();
  await loginRequest;
  await expect(page.getByRole('alert')).toContainText('로그인 정보가 올바르지 않습니다.');
  expect(page.url()).not.toContain('password=');
});

test('login without JavaScript keeps submit disabled until hydration', async ({ browser }) => {
  const context = await browser.newContext({ javaScriptEnabled: false });
  try {
    const page = await context.newPage();
    await page.goto('/login');
    await expect(page.getByRole('button', { name: '로그인' })).toBeDisabled();
  } finally {
    await context.close();
  }
});
test('session expiration redirects safely to login', async ({ page }) => {
  await mockApi(page, { authenticated: false });
  await page.goto('/guide');
  await expect(page).toHaveURL(/\/login$/);
});

for (const width of [360, 768, 1440]) {
  test('authenticated shell and keyboard access at width ' + width, async ({ page }, testInfo) => {
    await mockApi(page);
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/guide');
    await expect(page.getByRole('navigation', { name: '주요 메뉴' })).toBeVisible();
    const skip = page.getByRole('link', { name: '본문으로 건너뛰기' });
    await skip.focus();
    await expect(skip).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#main-content')).toBeFocused();
    const size = await page.evaluate(() => ({ document: document.documentElement.scrollWidth, viewport: innerWidth }));
    expect(size.document).toBeLessThanOrEqual(size.viewport + 1);
    await page.screenshot({ path: testInfo.outputPath('guide-' + width + '.png'), fullPage: true });
  });
}

test('notice list traverses beyond the 100th result through server pagination', async ({ page }) => {
  await mockApi(page);
  const offsets: number[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/v1/notices?')) {
      offsets.push(Number(new URL(request.url()).searchParams.get('offset') ?? 0));
    }
  });
  await page.goto('/notices');
  await expect(page.getByText('테스트 공고 1', { exact: true })).toBeVisible();
  const next = page.getByRole('button', { name: '다음 페이지' });
  const pageCount = Math.ceil(101 / NOTICE_PAGE_SIZE);
  for (let i = 1; i < pageCount; i++) {
    await next.click();
    await expect(page.getByText((i + 1) + ' / ' + pageCount + ' 페이지')).toBeVisible();
  }
  await expect(page.getByText('테스트 공고 101', { exact: true })).toBeVisible();
  expect(offsets).toContain(100);
});

test('server errors show an actionable retry instead of false success', async ({ page }) => {
  await mockApi(page, { noticesFail: true });
  await page.goto('/notices');
  await expect(page.getByText('일시적으로 공고를 조회할 수 없습니다.')).toBeVisible();
  await expect(page.getByRole('button', { name: /다시 시도/ })).toBeEnabled();
});
test('ML recommendation mock shows rank, score, model version, and independent qualification', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/companies', route => route.fulfill({ status: 200, json: [{
    id: 'company-a', name: '로컬 테스트 회사',
  }] }));
  await page.route('**/api/v1/companies/company-a/notice-matches?*', route => route.fulfill({
    status: 200, json: { company_id: 'company-a', analyzed_notice_count: 1,
      returned_count: 1, items: [{
        notice_id: 'notice-a', bid_notice_no: '2026-0001', title: '로컬 E2E 공고',
        institution_name: '테스트 기관', version_number: 1, analysis_run_id: 'analysis-a',
        analysis_status: 'SUCCEEDED', overall_status: 'insufficient_data',
        satisfied_count: 1, unknown_count: 1, unsatisfied_count: 0,
        requirement_count: 2, evidence_count: 1, analyzed_at: '2026-10-09T00:00:00',
      }], note: 'LOCAL MOCK' },
  }));
  await page.route('**/api/v1/ml/recommendations?*', route => route.fulfill({
    status: 200, json: { company_id: 'company-a', items: [{
      notice_id: 'notice-a', bid_notice_no: '2026-0001', title: '로컬 E2E 공고',
      rank: 1, relevance_score: 0.88, model_version: 'mock-model-v1',
      reasons: ['업종과 공고 내용의 의미적 유사성'],
      evidence_href: '/api/v1/notices/notice-a/versions/1/documents/document-a/text',
    }] },
  }));
  await page.goto('/recommendations');
  await expect(page.getByText('MOCK · 실제 모델 결과 아님')).toBeVisible();
  await expect(page.getByText('88%')).toBeVisible();
  await expect(page.getByText('모델 버전: mock-model-v1')).toBeVisible();
  await expect(page.getByRole('region', { name: 'ML 추천 순위' }).getByText('기존 자격판정: 확인 필요')).toBeVisible();
  await expect(page.getByRole('link', { name: /추천 근거 원문 열기/ }))
    .toHaveAttribute('href', /\/api\/v1\/notices\//);
});