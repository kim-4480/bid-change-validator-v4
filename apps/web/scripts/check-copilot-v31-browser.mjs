/* Actual React panel, mocked product API; no DB or live model traffic. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

async function loadPlaywright() {
  const moduleRoot = process.env.PLAYWRIGHT_MODULE;
  if (!moduleRoot) return import('playwright');
  const entry = moduleRoot.endsWith('/index.js') || moduleRoot.endsWith('\\index.js')
    ? moduleRoot
    : `${moduleRoot.replace(/[\\/]$/, '')}/index.js`;
  return import(pathToFileURL(entry).href);
}

const loadedPlaywright = await loadPlaywright();
const playwright = loadedPlaywright.default ?? loadedPlaywright;
const chromium = loadedPlaywright.chromium ?? playwright.chromium;
if (!chromium) throw Error('Playwright chromium export not found');

(async () => {
  const origin = process.env.COPILOT_UI_URL;
  if (!origin || !['localhost', '127.0.0.1'].includes(new URL(origin).hostname)) throw Error('Explicit loopback UI required');
  const replay = JSON.parse(fs.readFileSync(process.env.COPILOT_REPLAY_FILE, 'utf8'));
  const envelope = structuredClone(replay[0]);
  const s = envelope.sources[0].scope;
  const company = { id: s.company_id, name: '합성 검증 회사', industries: [], performances: [], certifications: [], staff: null };
  const item = { id: s.case_id, company_id: s.company_id, notice_id: s.notice_id, bid_notice_no: 'V31-FIXTURE',
    notice_title: 'v3.1 합성 검토 공고', title: 'v3.1 합성 검토 공고', status: 'DRAFT', baseline_version_number: 1, current_version_number: 1, documents: [] };
  const version = { id: s.notice_version_id, version_number: 1, documents: [], is_current: true };
  const catalog = { contract_version: 'copilot-guided-jobs-v1', jobs: [
    { job_id: 'changed_notice', label: '변경 공고 대응', order: 1, questions: [
      { question_id: 'what_changed', label: '무엇이 바뀌었나요?', order: 1, answer_scope: '변경 설명', completion_criteria: ['변경 확인'], required_tools: ['READ_CHANGES'], availability: 'AVAILABLE', unavailable_reason: null },
      { question_id: 'company_impact', label: '우리 회사에 어떤 영향이 있나요?', order: 2, answer_scope: '회사 영향', completion_criteria: ['영향 확인'], required_tools: ['READ_CHANGES'], availability: 'AVAILABLE', unavailable_reason: null },
      { question_id: 'next_checks', label: '무엇을 확인해야 하나요?', order: 3, answer_scope: '확인사항', completion_criteria: ['다음 행동'], required_tools: ['READ_CHECKS'], availability: 'AVAILABLE', unavailable_reason: null },
    ] },
    { job_id: 'bid_preparation', label: '입찰 참여 준비', order: 2, questions: [
      { question_id: 'documents_deadlines_methods', label: '필요한 서류·기한·방법은?', order: 1, answer_scope: '서류', completion_criteria: ['서류 확인'], required_tools: ['READ_DOCUMENT'], availability: 'AVAILABLE', unavailable_reason: null },
      { question_id: 'preparation_order', label: '준비 순서는?', order: 2, answer_scope: '순서', completion_criteria: ['순서 확인'], required_tools: ['READ_DOCUMENT'], availability: 'AVAILABLE', unavailable_reason: null },
      { question_id: 'unresolved', label: '아직 확인하지 못한 것은?', order: 3, answer_scope: '미확인', completion_criteria: ['미확인 확인'], required_tools: ['READ_CHECKS'], availability: 'AVAILABLE', unavailable_reason: null },
    ] },
  ] };
  const requests = [], semanticHeaders = [], errors = [], outbound = [];
  const browser = await chromium.launch({ headless: true, channel: process.env.COPILOT_BROWSER_CHANNEL || 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.pathname.startsWith('/api/v1/')) {
      const p = url.pathname;
      const headers = { 'access-control-allow-origin': origin, 'access-control-allow-credentials': 'true',
        'access-control-allow-headers': 'Content-Type,X-Copilot-Semantic-Processing', 'access-control-allow-methods': 'GET,POST,OPTIONS' };
      const reply = body => route.fulfill({ status: 200, headers, contentType: 'application/json', body: JSON.stringify(body) });
      if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
      if (p.endsWith('/copilot/jobs')) return reply(catalog);
      if (p.endsWith('/copilot/chat')) {
        const payload = request.postDataJSON();
        requests.push(payload);
        semanticHeaders.push(request.headers()['x-copilot-semantic-processing']);
        const response = structuredClone(envelope);
        response.context_revision = requests.length;
        response.guided = payload.job_id && payload.question_id ? {
          job_id: payload.job_id, question_id: payload.question_id, status: 'COMPLETE',
          next_question_id: payload.question_id === 'what_changed' ? 'company_impact' : null,
        } : null;
        return reply({ answer: response.claims.map(c => c.text).join('\n'), intent: 'UNKNOWN', envelope: response,
          product_state: null, actions: [], citations: [], sources: [], warnings: [], external_processing_used: false, external_processing_scope: null });
      }
      if (p.endsWith('/actions/confirm')) throw Error('Browser must not confirm any write');
      if (p === '/api/v1/auth/me') return reply({ id: 'fixture-user', username: 'fixture', role: 'USER', company_id: company.id, company_name: company.name });
      if (p === '/api/v1/companies') return reply([company]);
      if (p === '/api/v1/preflight-cases') return reply({ items: [item], total: 1, limit: 100, offset: 0 });
      if (p === `/api/v1/preflight-cases/${s.case_id}`) return reply(item);
      if (p.endsWith('/versions')) return reply([version]);
      if (p.endsWith('/qualification-analyses') || p.endsWith('/qualification-judgment-runs') || p.endsWith('/qualification-questions')) return reply([]);
      if (p === `/api/v1/notices/${s.notice_id}`) return reply({ id: s.notice_id, title: item.notice_title, latest: version });
      return reply({ items: [], total: 0 });
    }
    if (url.origin !== origin && !url.protocol.startsWith('data')) { outbound.push(request.url()); return route.abort(); }
    return route.continue();
  });
  try {
    await page.goto(`${origin}/qualification?caseId=${s.case_id}`);
    await page.getByRole('heading', { name: item.notice_title, exact: true }).waitFor();
    await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
    await page.locator('#copilot-panel[open]').waitFor();
    assert.equal(await page.locator('#copilot-semantic-processing').isChecked(), false, 'AI detail processing must be opt-in');
    await page.getByRole('button', { name: '1. 무엇이 바뀌었나요?', exact: true }).click();
    await page.locator('[data-copilot-version="3.1"]').waitFor();
    assert.equal(requests[0].response_version, '3.1');
    assert.equal(requests[0].job_id, 'changed_notice');
    assert.equal(requests[0].question_id, 'what_changed');
    assert.equal(semanticHeaders[0], undefined, 'v3.1 must not imply semantic/model processing consent');
    assert(await page.getByText('공고일 기준 2년 내 2개 이상', { exact: false }).first().isVisible());
    assert.equal(await page.getByText('답변 검토 상태:', { exact: false }).count(), 0);
    await page.locator('[data-copilot-version="3.1"] .copilot-evidence-toggle').first().click();
    assert(await page.locator('[data-copilot-version="3.1"] blockquote').first().isVisible());
    assert(await page.getByRole('button', { name: '추천 질문 6개 보기', exact: true }).isVisible());
    await page.locator('#copilot-question').fill('1224와 1227은 무슨 차이야?');
    await page.locator('#copilot-question').press('Enter');
    await page.waitForFunction(() => document.querySelectorAll('[data-copilot-version="3.1"]').length === 2);
    assert.equal(requests[1].response_version, '3.1');
    assert.equal(requests[1].message, '1224와 1227은 무슨 차이야?');
    assert.equal(requests[1].job_id, undefined, 'Free text must not impersonate a guided question');
    assert.equal(requests[1].question_id, undefined, 'Free text must not impersonate a guided question');
    assert.equal(semanticHeaders[1], undefined, 'Free text must preserve semantic opt-out');
    assert.equal(requests[1].conversation_id, envelope.conversation_id);
    assert.equal(requests[1].context_revision, 1);
    assert.equal(requests[1].allow_external_processing, undefined, 'Free text must not silently enable document processing');
    await page.locator('#copilot-panel').screenshot({ path: process.env.COPILOT_SCREENSHOT_FILE });
    await page.getByRole('button', { name: '새 대화', exact: true }).click();
    assert.equal(await page.locator('[data-copilot-version="3.1"]').count(), 0);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ status: 'PASS', chat_requests: requests.length, case_id: s.case_id,
      semantic_opt_in: false, page_errors: errors, blocked_external_requests: outbound.length,
      scope: 'actual panel with mock API; no live DB/model' }));
  } catch (error) {
    await page.screenshot({ path: process.env.COPILOT_SCREENSHOT_FILE });
    console.error(JSON.stringify({ errors, text: (await page.locator('body').innerText()).slice(-3000) }));
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
