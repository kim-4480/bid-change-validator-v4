// Verify that v3.1 orchestration stays on while semantic-routing and document-RAG consent remain explicit HTTP boundaries.
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
    name => load(resolve(dirname(file), `${name}.ts`)), compiled, compiled.exports,
  );
  return compiled.exports;
}

const { ConversationStore, inferE1Intent } = load(resolve(root, 'lib/copilot-conversation.ts'));
const { copilotMocks: m } = load(resolve(root, 'lib/copilot-mocks.ts'));
const id = m.eligible.product_state.provenance.case_id;
const calls = [];
const originalFetch = globalThis.fetch;

function fetchUrl(input) {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  if (input instanceof Request) return input.url;
  throw new TypeError('Unexpected fetch input');
}

function jsonBody(init) {
  if (typeof init?.body !== 'string') throw new TypeError('Expected a string request body');
  return JSON.parse(init.body);
}

try {
  globalThis.fetch = async (url, init) => {
    calls.push({ url: fetchUrl(url), init, body: jsonBody(init) });
    return {
      ok: true,
      status: 200,
      json: async () => structuredClone(m.eligible),
    };
  };

  const store = new ConversationStore();
  await store.ask(id, '회사 허가와 제품 허가를 구분해줘', undefined, 'QUALIFICATION', false, false);
  await store.ask(id, '평가점수와 필수 참가요건을 구분해줘', undefined, 'QUALIFICATION', true, false);
  await store.ask(id, '중소기업 확인서 제출 시점이 언제야?', undefined, 'QUALIFICATION', true, true);

  assert.equal(calls.length, 3);
  assert.equal(calls[0].url.endsWith('/api/v1/copilot/chat'), true);

  // v3.1 conversation state/targets are independent from model-processing consent.
  for (const call of calls) assert.equal(call.body.response_version, '3.1');

  // Semantic routing consent is a header, never a JSON product field.
  assert.equal(calls[0].init.headers['X-Copilot-Semantic-Processing'], undefined);
  assert.equal(calls[1].init.headers['X-Copilot-Semantic-Processing'], 'true');
  assert.equal(calls[2].init.headers['X-Copilot-Semantic-Processing'], 'true');
  for (const call of calls) assert.equal('semantic_processing' in call.body, false);

  // Document RAG is a separate explicit payload opt-in. Internal UI state is not serialized.
  assert.equal(calls[0].body.public_document_question, undefined);
  assert.equal(calls[0].body.allow_external_processing, undefined);
  assert.equal(calls[1].body.public_document_question, undefined);
  assert.equal(calls[1].body.allow_external_processing, undefined);
  assert.equal(calls[2].body.public_document_question, '중소기업 확인서 제출 시점이 언제야?');
  assert.equal(calls[2].body.allow_external_processing, true);
  for (const call of calls) assert.equal('document_processing' in call.body, false);

  assert.equal(calls[2].body.user_input, undefined);
  assert.equal(inferE1Intent('1224와 1227은 무슨 차이야?'), 'CHANGED_NOTICE');
  assert.equal(inferE1Intent('이전 내용과 비교해줘'), 'CHANGED_NOTICE');
  console.log('PASS v3.1 stays active while semantic and document-RAG consent remain separate');
} finally {
  globalThis.fetch = originalFetch;
}
