(async () => {
// Requires the isolated synthetic case. Confirm is aborted before it reaches the API.
const assert = (await import('node:assert/strict')).default;
const { pathToFileURL } = await import('node:url');
const { resolve } = await import('node:path');
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE, 'index.mjs')).href : 'playwright');
  const url = new URL(process.env.COPILOT_TEST_URL);
  assert(['localhost', '127.0.0.1'].includes(url.hostname));
  const caseId = url.searchParams.get('caseId');
  assert(caseId);
  const browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_BROWSER_CHANNEL ? { channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    let confirms = 0;
    await page.route('**/api/v1/copilot/actions/confirm', async route => {
      confirms++;
      await route.abort('timedout');
    });
    await page.goto(url.origin + '/ask-back?caseId=' + caseId);
    await page.getByRole('button', { name: '이 요건 답변 입력 · 아직 저장 안 함' }).last().click();
    const card = page.getByRole('region', { name: '공통 작업 확인' });
    await card.getByLabel('이 요건을 충족하나요?').selectOption('true');
    await card.getByLabel('증빙을 보유하고 있나요?').selectOption('false');
    await card.getByLabel('답변 값 (필요한 경우)').fill('600000000');
    await card.getByRole('button', { name: '반영 제안 받기 · 아직 저장 안 함' }).click();
    await card.getByRole('button', { name: '내용 확인 후 실행' }).waitFor();
    await page.getByRole('link', { name: '참가자격', exact: true }).click();
    await page.waitForURL('**/qualification?**');
    await card.getByRole('button', { name: '내용 확인 후 실행' }).click();
    await card.getByText('저장 성공 여부를 확인할 수 없습니다. 자동으로 다시 실행하지 않습니다. 현재 결과를 조회해 확인해 주세요.', { exact: true }).waitFor();
    assert(await page.getByRole('button', { name: '다시 검토', exact: true }).isDisabled());
    assert(await page.getByRole('button', { name: '전체 변경 요건 재검증 제안' }).isDisabled());
    await card.getByRole('button', { name: '결과 조회만 다시 시도' }).click();
    const message = '현재 판정을 조회했습니다. 이 조회만으로 이전 요청의 성공을 확정할 수 없어 재실행은 잠겨 있습니다.';
    await card.getByText(message, { exact: true }).waitFor();
    await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
    const panel = page.locator('#copilot-panel');
    await panel.getByText(message, { exact: true }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.querySelector('#copilot-panel').matches(':modal'));
    assert((await panel.boundingBox()).width <= 390);
    await page.getByRole('button', { name: '도우미 닫기' }).click();
    await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
    await panel.getByText(message, { exact: true }).waitFor();
    assert(await panel.getByLabel('이 요건을 충족하나요?').isDisabled());
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.waitForFunction(() => !document.querySelector('#copilot-panel').matches(':modal'));
    await page.getByRole('button', { name: '도우미 닫기' }).click();
    await page.getByRole('link', { name: '변경 이력', exact: true }).click();
    await card.getByText(message, { exact: true }).waitFor();
    assert.equal(confirms, 1);
    console.log('PASS timeout/unknown, readonly refresh never infers success, qualification lock, cross-page state, modal Drawer and reopen; API writes=0');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
