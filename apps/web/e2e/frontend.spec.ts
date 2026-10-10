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
        status_counts: { core_met: 0, core_unmet: 0, unreviewed: 101, needs_review: 0 },
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
test('guide uses a single shared title band and keeps complete content', async ({ page }) => {
  await mockApi(page);
  await page.goto('/guide');
  await expect(page.locator('nav.app-primary-nav')).toBeVisible();
  await expect(page.locator('.app-title-band h1')).toHaveText('이용안내');
  await expect(page.getByRole('heading', { name: '이용안내', level: 1 })).toHaveCount(1);
  await expect(page.locator('#main-content ol > li')).toHaveCount(3);
  await expect(page.locator('#main-content main section')).toHaveCount(5);

  // A client-side transition must not reintroduce the fallback title.
  await page.locator('nav.app-primary-nav a[href="/notices"]').click();
  await expect(page).toHaveURL(/\/notices$/);
  await page.locator('nav.app-primary-nav a[href="/guide"]').click();
  await expect(page).toHaveURL(/\/guide$/);
  await expect(page.locator('.app-title-band')).toHaveCount(1);
  await expect(page.locator('.app-title-band h1')).toHaveText('이용안내');
});

test('title bands share qualification spacing across four product pages', async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  const pages = [
    ['/qualification', '참가자격 검토', '판정한 모든 항목에 공고 원문 근거를 함께 표시합니다.', '홈 › 내 입찰 건 › 참가자격 검토'],
    ['/company', '회사 프로필', '공고 판정에 사용하는 회사 값을 출처와 함께 관리합니다.', '홈 › 회사 프로필'],
    ['/recommendations', 'AI 추천', '모델의 연관성 추천과 기존 자격판정 결과를 구분해 확인합니다.', '홈 › 공고 추천'],
    ['/guide', '이용안내', '공고를 찾아 참가 자격을 확인하고, 공고가 바뀌면 다시 검증합니다.', '홈 › 이용안내'],
  ];
  const positions = [];
  for (const [route, title, description, crumb] of pages) {
    await page.goto(route);
    const band = page.locator('.app-title-band');
    await expect(band).toHaveCount(1);
    await expect(band).toHaveCSS('height', '142px');
    await expect(band.locator('h1')).toHaveText(title);
    await expect(band.locator('p').first()).toHaveText(description);
    await expect(band.locator('p').last()).toHaveText(crumb);
    positions.push(await band.evaluate(section => {
      const top = section.getBoundingClientRect().top;
      return [section.querySelector('h1'), section.querySelector('h1 + p'), section.querySelector(':scope > div > p:last-child')]
        .map(el => Math.round(el!.getBoundingClientRect().top - top));
    }));
  }
  for (const position of positions.slice(1)) expect(position).toEqual(positions[0]);
});

test('cached notice list survives route round trip without another GET or empty-state flash', async ({ page }) => {
  let noticeGets = 0;
  let companyGets = 0;
  await mockApi(page);
  page.on('request', (request) => {
    const u = new URL(request.url());
    if (request.method() !== 'GET') return;
    if (u.pathname === '/api/v1/notices') noticeGets++;
    if (u.pathname === '/api/v1/companies') companyGets++;
  });
  await page.goto('/notices');
  await expect(page.getByText('2026-0001').first()).toBeVisible({ timeout: 20_000 });
  const before = { noticeGets, companyGets };
  expect(before.noticeGets).toBe(1);
  expect(before.companyGets).toBe(1);

  for (let index = 0; index < 3; index++) {
    await page.locator('nav.app-primary-nav a[href="/guide"]').click();
    await expect(page).toHaveURL(/\/guide$/);
    await page.locator('nav.app-primary-nav a[href="/notices"]').click();
    await expect(page).toHaveURL(/\/notices$/);
    await expect(page.getByText('2026-0001').first()).toBeVisible();
    await expect(page.getByLabel('?? ?? ???? ?')).toHaveCount(0);
  }
  expect(noticeGets).toBe(before.noticeGets);
  expect(companyGets).toBe(before.companyGets);
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
    await expect(page.getByRole('navigation', { name: '주요 메뉴' })).toBeVisible({ timeout: 15_000 });
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
test('ML POST contract distinguishes learned rank from qualification (MOCK)', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/companies', route => route.fulfill({
    status: 200, json: [{ id: 'company-a', name: '로컬 테스트 회사' }],
  }));
  await page.route('**/api/v1/recommendations/ml', route => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toMatchObject({ company_id: 'company-a', limit: 50 });
    return route.fulfill({ status: 200, json: {
      model_version: 'mock-model-v1', dataset_version: 'mock-dataset',
      scoring_source: 'local_lightgbm', input_sha256: null, fallback_reason: null,
      fallback_used: false, total_valid_candidates: 2,
      note: 'Ranking is not a probability', items: [{
        notice_id: 'notice-a', title: '로컬 E2E 공고', rank: 1, relevance_score: 0.88,
        reason: 'Text relevance', version_number: 1, analysis_run_id: null,
        analysis_version: null, analysis_status: 'SUCCEEDED', qualification_state: 'core_met',
        qualification_reason: 'Verified', rule_version: 'test', is_stale: false,
        deadline_source: 'explicit', effective_deadline: '2026-10-10T00:00:00Z',
      }], needs_review_items: [{
        notice_id: 'notice-b', title: '추가 확인 공고', rank: 1, relevance_score: 0.76,
        reason: 'Text relevance', version_number: 1, analysis_run_id: null,
        analysis_version: null, analysis_status: 'UNKNOWN', qualification_state: 'needs_review',
        qualification_reason: 'Insufficient evidence', rule_version: null, is_stale: false,
        deadline_source: 'assumed_40_days', effective_deadline: '2026-10-20T00:00:00Z',
      }],
    } });
  });
  await page.goto('/recommendations');
  await expect(page.getByText('MOCK · 실제 모델 결과 아님')).toBeVisible();
  await expect(page.getByText('학습 모델 기반 연관성 순위')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('0.880')).toBeVisible();
  await expect(page.getByText('핵심 요건 충족')).toBeVisible();
  await expect(page.getByRole('heading', { name: '확인 필요 공고' })).toBeVisible();
  await expect(page.getByText('추가 확인 공고')).toBeVisible();
  await expect(page.getByRole('link', { name: /공고 상세·첨부 원문/ }))
    .toHaveAttribute('href', '/notices/notice-a');
  await expect(page.getByText('88%')).toHaveCount(0);
});

test('lexical fallback never claims a trained model (MOCK)', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/companies', route => route.fulfill({
    status: 200, json: [{ id: 'company-a', name: '로컬 회사' }],
  }));
  await page.route('**/api/v1/recommendations/ml', route => route.fulfill({
    status: 200, json: {
      model_version: null, dataset_version: null, scoring_source: 'lexical_fallback',
      input_sha256: null, fallback_reason: 'model_not_configured',
      fallback_used: true, total_valid_candidates: 0,
      note: 'Not a trained model', items: [], needs_review_items: [],
    },
  }));
  await page.goto('/recommendations');
  await expect(page.getByText('학습 모델 미적용 — 키워드 기반 대체 순위')).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('검증된 핵심 요건 충족 추천 결과가 없습니다. 확인 필요 공고는 아래에 별도로 표시합니다.')).toBeVisible();
});

test('admin view denies non-admin and does not invoke mutations (MOCK)', async ({ page }) => {
  await mockApi(page);
  await page.goto('/admin');
  await expect(page.getByRole('alert')).toContainText('관리자만 접근할 수 있습니다.');
  await page.route('**/api/v1/auth/me', route => route.fulfill({
    status: 200, json: { ...mockUser, role: 'SYSTEM_ADMIN' },
  }));
  await page.route('**/api/v1/admin/history-jobs?*', route => route.fulfill({ status: 200, json: [] }));
  await page.route('**/api/v1/admin/processing-jobs?*', route => route.fulfill({ status: 200, json: [] }));
  await page.route('**/api/v1/admin/relevance-labels?*', route => route.fulfill({ status: 200, json: [] }));
  const writes: string[] = [];
  page.on('request', request => {
    if (!['GET', 'HEAD'].includes(request.method())) writes.push(request.method());
  });
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: '공고 이력 수집 작업' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '공고 차수별 처리 작업' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '기업–공고 연관성 사람 검수' })).toBeVisible();
  await expect(page.getByRole('status')).toContainText('임베딩·LLM 워커는 기본 비활성');
  expect(writes).toEqual([]);
});

test('notice detail renders empty original instead of pretending extraction succeeded (MOCK)', async ({ page }) => {
  await mockApi(page);
  const notice = {
    id: 'notice-a', bid_notice_no: '2026-1', title: '테스트 공고 상세',
    announcing_institution_name: '기관', demanding_institution_name: null,
    current_version: 1, latest: {
      id: 'v1', version_number: 1, is_current: true, bid_closed_at: null, documents: [],
    },
  };
  await page.route('**/api/v1/notices/notice-a', route => route.fulfill({ status: 200, json: notice }));
  await page.route('**/api/v1/notices/notice-a/versions', route => route.fulfill({ status: 200, json: [notice.latest] }));
  await page.goto('/notices/notice-a');
  await expect(page.getByRole('heading', { name: '테스트 공고 상세' })).toBeVisible();
  await expect(page.getByText('해당 버전의 첨부 원문이 없습니다.')).toBeVisible();
});
test('seven existing product routes remain reachable with local API mocks', async ({ page }) => {
  await mockApi(page);
  for (const route of ['/notices', '/qualification', '/ask-back', '/evidence', '/evaluation', '/changes', '/company']) {
    await page.goto(route);
    await expect(page.locator('#main-content')).toBeVisible();
    await expect(page.getByRole('navigation', { name: '주요 메뉴' })).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(new RegExp(route.replace('/', '\\/') + '$'));
  }
});
test('Copilot never submits a question without a selected case (MOCK)', async ({ page }) => {
  await mockApi(page);
  const mutations: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/v1/copilot') && request.method() !== 'GET') mutations.push(request.url());
  });
  await page.goto('/qualification');
  await page.getByRole('button', { name: /AI Copilot/ }).click();
  await expect(page.getByRole('dialog', { name: 'AI Copilot' })).toBeVisible();
  await expect(page.getByRole('button', { name: '질문 보내기' })).toBeDisabled();
  expect(mutations).toEqual([]);
});

test('admin navigation does not overflow narrow mobile view (MOCK)', async ({ page }) => {
  await mockApi(page);
  await page.route('**/api/v1/auth/me', route => route.fulfill({
    status: 200, json: { ...mockUser, role: 'SYSTEM_ADMIN' },
  }));
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto('/admin');
  await expect(page.getByRole('heading', { name: '운영 작업 관리' })).toBeVisible();
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(width).toBeLessThanOrEqual(361);
});
test('client navigation preserves document and avoids repeated auth checks', async ({ page }) => {
  let authChecks = 0;
  let documentLoads = 0;
  await mockApi(page);
  page.on('request', request => {
    if (request.resourceType() === 'document') documentLoads++;
    if (new URL(request.url()).pathname === '/api/v1/auth/me') authChecks++;
  });
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));

  await page.goto('/guide');
  await expect(page.locator('nav.app-primary-nav')).toBeVisible();
  await page.evaluate(() => { (window as Window & { __navigationProof?: string }).__navigationProof = 'kept'; });
  const initialDocuments = documentLoads;

  for (let index = 0; index < 20; index++) {
    const pathname = index % 2 ? '/guide' : '/notices';
    await page.locator(`nav.app-primary-nav a[href="${pathname}"]`).click();
    await expect(page).toHaveURL(new RegExp(`${pathname}$`));
  }
  await page.goBack();
  await page.goForward();
  await expect(page).toHaveURL(/\/guide$/);

  expect(await page.evaluate(() => (window as Window & { __navigationProof?: string }).__navigationProof))
    .toBe('kept');
  expect(documentLoads).toBe(initialDocuments);
  expect(authChecks).toBe(1);
  expect(errors).toEqual([]);
});
