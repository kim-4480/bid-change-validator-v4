/** Isolated, non-mock browser → FastAPI → PostgreSQL smoke check.
 *
 * Start an isolated API and Vinext server first. Playwright forwards only
 * same-origin /api/v1 requests to the real API; it never fabricates responses.
 * This must never be pointed at AWS or a shared database.
 */
import assert from 'node:assert/strict';
import { chromium } from '@playwright/test';

const web = process.env.BIDCHECK_E2E_WEB_URL;
const api = process.env.BIDCHECK_E2E_API_URL;
const username = process.env.BIDCHECK_E2E_USERNAME;
const password = process.env.BIDCHECK_E2E_PASSWORD;
if (!web || !api || !username || !password) {
  throw new Error('BIDCHECK_E2E_WEB_URL, API_URL, USERNAME and PASSWORD are required');
}
for (const value of [web, api]) {
  const url = new URL(value);
  if (!['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname)) {
    throw new Error('This smoke check may target only loopback hosts');
  }
}

const browser = await chromium.launch();
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = [];
  const browserErrors = [];
  page.on('pageerror', (error) => browserErrors.push(error.message));
  page.on('requestfailed', (request) => browserErrors.push(`${request.method()} ${request.url()}: ${request.failure()?.errorText}`));
  await page.route('**/api/v1/**', async (route) => {
    const original = new URL(route.request().url());
    const destination = new URL(`${original.pathname}${original.search}`, api);
    seen.push([original.pathname, 'requested']);
    const response = await route.fetch({ url: destination.href });
    seen.push([original.pathname, response.status()]);
    await route.fulfill({ response });
  });

  await page.goto(new URL('/login', web).href);
  await page.waitForFunction(() => !document.querySelector('button[type="submit"]')?.disabled, undefined, { timeout: 15_000 });
  await page.getByLabel('아이디').fill(username);
  await page.getByLabel('비밀번호').fill(password);
  await page.getByRole('button', { name: '로그인', exact: true }).click();
  try {
    await page.waitForURL('**/company', { timeout: 15_000 });
  } catch (error) {
    console.error('Login did not navigate; API statuses:', seen);
    console.error('Current URL:', page.url());
    console.error('Browser errors:', browserErrors);
    console.error('Visible alert:', await page.getByRole('alert').allTextContents());
    throw error;
  }
  await page.goto(new URL('/notices', web).href);
  await page.getByText('Isolated Service Notice').first().waitFor({ timeout: 15_000 });
  await page.goto(new URL('/recommendations', web).href);
  await page.getByText('학습 모델 미적용 — 키워드 기반 대체 순위').waitFor({ timeout: 15_000 });
  await page.getByRole('heading', { name: '확인 필요 공고' }).waitFor();
  await page.getByText('Isolated Service Notice').first().waitFor();
  await page.goto(new URL('/admin', web).href);
  await page.getByRole('heading', { name: '공고 차수별 처리 작업' }).waitFor();

  for (const path of ['/api/v1/auth/login', '/api/v1/auth/me', '/api/v1/notices',
    '/api/v1/companies', '/api/v1/recommendations/ml', '/api/v1/admin/processing-jobs']) {
    assert(seen.some(([actual, status]) => actual === path && status === 200), `${path} did not return 200`);
  }
  console.log('PASS: real browser → FastAPI → isolated PostgreSQL; lexical fallback and admin reads');
} finally {
  await browser.close();
}
