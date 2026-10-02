// No test framework or emitted files: use the already installed TypeScript compiler.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInThisContext } from 'node:vm';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const modules = new Map();
function load(file) {
  if (modules.has(file)) return modules.get(file).exports;
  const compiled = { exports: {} };
  modules.set(file, compiled);
  const { outputText } = ts.transpileModule(readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: file,
  });
  runInThisContext(`(function(require,module,exports){${outputText}\n})`, { filename: file })(
    (name) => load(resolve(dirname(file), `${name}.ts`)), compiled, compiled.exports,
  );
  return compiled.exports;
}

const { copilotMocks, staleActionErrorMock } = load(resolve(root, 'lib/copilot-mocks.ts'));
if (process.argv.includes('--fixtures')) {
  console.log(JSON.stringify(copilotMocks));
} else {
  const api = load(resolve(root, 'lib/copilot-api.ts'));
  const vm = load(resolve(root, 'lib/copilot-view-model.ts'));
  const { ApiError } = load(resolve(root, 'lib/api.ts'));
  const before = JSON.stringify(copilotMocks);
  assert.equal(vm.getCopilotStatusLabel('insufficient_data'), '확인 필요');
  assert.equal(vm.getSourceLocationLabel(copilotMocks.productEvidence.sources[0]), '조항 2 · 섹션 1 문단 3');
  assert.equal(vm.getSourceLocationLabel(copilotMocks.documentRag.sources[0]), '조항 2 · p.2, p.3');
  assert.equal(vm.getSourceLocationLabel({ ...copilotMocks.documentRag.sources[0], clause_label: null, source_locations: [], page: null }), '위치 정보 없음');
  const warnings = vm.getCopilotWarningItems(copilotMocks.documentRag);
  warnings.push('local edit');
  assert.equal(JSON.stringify(copilotMocks), before);
  const originalFetch = globalThis.fetch;
  const sent = [];
  try {
    globalThis.fetch = async (url, init) => {
      sent.push({ url, body: JSON.parse(init.body) });
      return new Response(JSON.stringify(copilotMocks.consentRequired), { status: 200 });
    };
    const request = { case_id: 'fixture', message: 'private message' };
    await api.sendCopilotMessage(request);
    assert.deepEqual(sent[0].body, request); // No copying message into public_document_question/opt-in.
    const proposal = copilotMocks.answerProposal.actions[0];
    const confirm = { confirmed: true, action: proposal };
    await api.confirmCopilotAction(confirm);
    assert.deepEqual(sent[1].body, confirm); // All expected context and input preserved.
    assert(sent[1].url.endsWith('/api/v1/copilot/actions/confirm'));
    let errorCalls = 0;
    globalThis.fetch = async () => {
      errorCalls++;
      return new Response(JSON.stringify(staleActionErrorMock), { status: 409 });
    };
    await assert.rejects(api.confirmCopilotAction(confirm), (error) => error instanceof ApiError
      && error.status === 409 && error.code === 'STALE_ACTION_CONTEXT' && error.message === staleActionErrorMock.error.message);
    assert.equal(errorCalls, 1); // A stale confirmation is never auto-retried.
    assert.equal(JSON.stringify(copilotMocks), before);
  } finally {
    globalThis.fetch = originalFetch;
  }

// Stateful checks reuse the existing compiler loader; no server or external data.
const { ConversationStore, validateSources, hasOrdinalReference } = load(resolve(root, 'lib/copilot-conversation.ts'));
assert.equal(hasOrdinalReference('첫 번째 조건 근거 보여줘'), true);
assert.equal(hasOrdinalReference('두번째 근거'), true);
assert.equal(hasOrdinalReference('그 조건 근거 보여줘'), false);
let resolveFirst;
const transportRequests = [];
const store = new ConversationStore(async request => {
  transportRequests.push(request);
  return new Promise(resolve => { resolveFirst = resolve; });
});
const waiting = store.ask('case-a', '현재 결과', 'QUALIFICATION_SUMMARY');
assert.equal(store.get('case-a').busy, true);
assert.equal(store.get('case-b').turns.length, 0);
await store.ask('case-a', 'duplicate');
assert.equal(transportRequests.length, 1);
store.focus('case-a', 'R2');
resolveFirst(copilotMocks.eligible);
await waiting;
assert.equal(store.get('case-a').turns[0].response, undefined, 'Late reply cannot override new focus');
assert.equal(store.get('case-a').focus, 'R2');
assert.equal(store.get('case-b').focus, null);
assert.equal(transportRequests[0].allow_external_processing, undefined);
assert.equal(transportRequests[0].public_document_question, undefined);
assert.throws(() => validateSources({ ...copilotMocks.eligible, answer: '[S99]', sources: [] }));

const evidenceResponse = structuredClone(copilotMocks.productEvidence);
validateSources(evidenceResponse);
const wrongQuote = JSON.parse(JSON.stringify(evidenceResponse));
wrongQuote.citations[0].evidence.quote = 'different text';
assert.throws(() => validateSources(wrongQuote));
const wrongVersion = JSON.parse(JSON.stringify(evidenceResponse));
wrongVersion.citations[0].evidence.notice_version_id = 'different-version';
assert.throws(() => validateSources(wrongVersion));
assert.throws(() => validateSources({ ...evidenceResponse, citations: [] }));
const missingReason = structuredClone(evidenceResponse);
missingReason.presentation = { conclusion: 'test', reasons: [{ text: 'test', evidence_refs: ['S99'] }], limitations: [] };
assert.throws(() => validateSources(missingReason));
const reordered = structuredClone(evidenceResponse);
reordered.citations = reordered.citations.map(source => Object.fromEntries(Object.entries(source).reverse()));
validateSources(reordered);
const oldReply = { status: 'RESOLVED', context_revision: 1, requirement_key: 'R2',
  visible_requirement_keys: ['R1', 'R2'], last_read_receipt: { kind: 'product', provenance: { judgment_run_id: 'old' } } };
let historicalRequest;
const history = new ConversationStore(async request => { historicalRequest = request; return copilotMocks.eligible; });
history.focus('history', 'R2', oldReply);
await history.ask('history', '그 조건 근거 보여줘', 'REQUIREMENT_EVIDENCE');
assert.equal(historicalRequest.requirement_key, 'R2');
assert.equal(historicalRequest.conversation_context.last_read_receipt.provenance.judgment_run_id, 'old');
// The first mock response intentionally has no visible targets. Restore the historical
// reply so the ordinal check isolates stale-focus precedence instead of mock-state loss.
history.focus('history', 'R2', oldReply);
await history.ask('history', '첫 번째 조건 근거 보여줘', 'REQUIREMENT_EVIDENCE');
assert.equal(historicalRequest.requirement_key, undefined, 'Explicit ordinal must override stale UI focus');
assert.deepEqual(historicalRequest.conversation_context.visible_requirement_keys, ['R1', 'R2']);
assert.match(readFileSync(resolve(root, 'components/copilot/panel.tsx'), 'utf8'), /ask\('그 조건 근거 보여줘'/);
console.log('Citation metadata identity, citation completeness, ordinal precedence and historical receipt checks passed.');

console.log('Conversation isolation, duplicate reads, late response, privacy and invalid reference checks passed.');

console.log('Copilot client/view-model checks passed; 11 response mocks + 1 error fixture. No network calls.');
}
