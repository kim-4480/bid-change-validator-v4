(async () => {
// Run against a separately started UI + isolated API; no writes are requested.
const assert = (await import('node:assert/strict')).default;
const { pathToFileURL } = await import('node:url');
const { resolve } = await import('node:path');
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE, 'index.mjs')).href : 'playwright');
  if (!process.env.COPILOT_TEST_URL) throw new Error('COPILOT_TEST_URL with an isolated fixture case is required');
  const browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_BROWSER_CHANNEL ? { channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const writes = [];
    page.on('request', r => { if (r.url().includes('/actions/confirm')) writes.push(r.url()); });
    await page.goto(process.env.COPILOT_TEST_URL);
    // Wait for workspace client data before using its hydrated controls.
    await page.getByRole('heading', { name: 'Golden 변경공고 자격검증', exact: true }).waitFor();
    await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
    await page.getByRole('button', { name: '우리 회사, 참여 가능해?', exact: true }).click();
    await page.getByText('현재 저장된 판정만으로는 참가 가능 여부를 확정할 수 없습니다.', { exact: true }).waitFor();
    await page.getByRole('button', { name: '무엇을 확인해야 해?', exact: true }).click();
    await page.getByText(new RegExp('저장된 판정의 확인 대상 [0-9]+건입니다.'), { exact: true }).waitFor();
    // An already answered requirement can still have evidence. The remaining
    // unknown performance fixture intentionally has no linked evidence.
    await page.getByRole('button', { name: '우리 회사, 참여 가능해?', exact: true }).click();
    await page.locator('.copilot-answer').last().getByText('현재 저장된 판정만으로는 참가 가능 여부를 확정할 수 없습니다.', { exact: true }).waitFor();
    await page.locator('.copilot-answer').last().locator('.copilot-reason').filter({ hasText: '등록' }).getByRole('button', { name: '이 요건 근거 보기' }).first().click();
    await page.getByText('선택한 요건에 연결된 공고문 원문입니다.', { exact: true }).waitFor();
    const answer = page.locator('.copilot-answer').last();
    await answer.locator('summary').click();
    await answer.getByRole('link', { name: /· 원문$/ }).first().click();
    await page.waitForURL('**/evidence?**');
    await page.getByText('선택한 요건에 연결된 공고문 원문입니다.', { exact: true }).waitFor();
    await page.getByRole('button', { name: '도우미 닫기' }).click();
    await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
    await page.getByText('선택한 요건에 연결된 공고문 원문입니다.', { exact: true }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('#copilot-panel').matches(':modal'));
    assert((await page.locator('#copilot-panel').boundingBox()).width <= 390);
    if (process.env.COPILOT_SCREENSHOT_DIR) await page.screenshot({ path: process.env.COPILOT_SCREENSHOT_DIR + '/copilot-mobile.png' });
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.waitForFunction(() => !document.querySelector('#copilot-panel').matches(':modal'));
    if (process.env.COPILOT_SCREENSHOT_DIR) await page.screenshot({ path: process.env.COPILOT_SCREENSHOT_DIR + '/copilot-desktop.png' });
    assert.equal(writes.length, 0);
    console.log('PASS: real backend read, evidence navigation, close/reopen, mobile/desktop, zero confirm requests');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
