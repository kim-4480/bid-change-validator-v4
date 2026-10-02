(async () => {
const assert = (await import('node:assert/strict')).default;
const { pathToFileURL } = await import('node:url');
const { resolve } = await import('node:path');
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE, 'index.mjs')).href : 'playwright');
  const url = process.env.COPILOT_TEST_URL;
  if (!url || process.env.COPILOT_ALLOW_ISOLATED_WRITE !== 'yes') throw Error('Explicit isolated write test opt-in required');
  const browser = await chromium.launch({ ...(process.env.PLAYWRIGHT_BROWSER_CHANNEL ? { channel: process.env.PLAYWRIGHT_BROWSER_CHANNEL } : {}), headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    let saved = false, failRefresh = true, count = 0, sent;
    await page.route('**/api/v1/copilot/actions/confirm', async route => {
      assert.equal(new URL(route.request().url()).origin, 'http://127.0.0.1:18000');
      count++; sent = route.request().postDataJSON();
      const response = await route.fetch();
      assert.equal(response.status(), 200);
      saved = true;
      await route.fulfill({ response });
    });
    await page.route('**/api/v1/copilot/chat', async route => {
      if (saved && failRefresh) await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":{"message":"forced read failure","code":"TEST_READ_FAILURE"}}' });
      else await route.continue();
    });
    const base = new URL(url), caseId = base.searchParams.get('caseId');
    await page.goto(base.origin + '/ask-back?caseId=' + caseId);
    await page.getByRole('button', { name: '이 요건 답변 입력 · 아직 저장 안 함' }).last().waitFor();
    await page.getByRole('button', { name: '이 요건 답변 입력 · 아직 저장 안 함' }).last().click();
    const card = page.locator('.app-shell-content').getByRole('region', { name: '공통 작업 확인' });
    await card.getByLabel('이 요건을 충족하나요?').selectOption('true');
    assert(await card.getByRole('button', { name: '반영 제안 받기 · 아직 저장 안 함' }).isDisabled());
    await card.getByLabel('증빙을 보유하고 있나요?').selectOption('false');
    await card.getByRole('button', { name: '반영 제안 받기 · 아직 저장 안 함' }).click();
    await card.getByRole('button', { name: '내용 확인 후 실행' }).waitFor();
    assert.equal(count, 0);
    // Layout navigation preserves pending proposal in both the detail page and panel.
    await page.getByRole('link', { name: '변경 이력', exact: true }).click();
    await page.waitForURL('**/changes?**');
    await card.getByRole('button', { name: '내용 확인 후 실행' }).waitFor();
    await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
    const panel = page.locator('#copilot-panel');
    assert.equal(await panel.getByRole('button', { name: '내용 확인 후 실행' }).count(), 0);
    await panel.getByLabel('공고 질문').fill('응');
    await panel.getByRole('button', { name: '질문 보내기' }).click();
    await page.waitForTimeout(300);
    assert.equal(count, 0, 'Natural language agreement must not confirm');
    await page.getByRole('button', { name: '도우미 닫기' }).click();
    await card.getByRole('button', { name: '내용 확인 후 실행' }).click();
    await card.getByText('반영은 완료됐지만 새 판정을 불러오지 못했습니다. 결과 조회만 다시 시도해 주세요.', { exact: true }).waitFor();
    assert.equal(count, 1);
    failRefresh = false;
    await card.getByRole('button', { name: '결과 조회만 다시 시도' }).click();
    await card.getByText('반영 후 새 판정 결과를 확인했습니다.', { exact: true }).waitFor();
    assert.equal(count, 1);
    // Direct API replay verifies the real server rejects reuse.
    const replay = await page.request.post('http://127.0.0.1:18000/api/v1/copilot/actions/confirm', { data: sent });
    assert.equal(replay.status(), 409);
    console.log('PASS real proposal/confirm, false preserved, page/panel shared state, natural yes=0 writes, refresh failure/recovery, replay409');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
