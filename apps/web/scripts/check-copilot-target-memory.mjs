// Regression: a non-target manual-review turn must not erase the last requirement list
// while the same Product Truth receipt is still current.
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

const { ConversationStore } = load(resolve(root, 'lib/copilot-conversation.ts'));
const { copilotMocks } = load(resolve(root, 'lib/copilot-mocks.ts'));

const receipt = {
  kind: 'product',
  provenance: {
    case_id: '00000000-0000-4000-8000-000000000001',
    notice_id: '00000000-0000-4000-8000-000000000002',
    notice_version_id: '00000000-0000-4000-8000-000000000003',
    version_number: 2,
    company_id: '00000000-0000-4000-8000-000000000004',
    analysis_run_id: '00000000-0000-4000-8000-000000000005',
    judgment_run_id: '00000000-0000-4000-8000-000000000006',
    analysis_status: 'SUCCEEDED',
    rule_version: 'qualification-rules-v0.2',
  },
};

function responseWithTargets(targets) {
  const response = structuredClone(copilotMocks.eligible);
  response.reply_context = {
    request_id: null,
    context_revision: 1,
    status: 'RESOLVED',
    requirement_key: null,
    visible_requirement_keys: targets,
    last_read_receipt: structuredClone(receipt),
  };
  return response;
}

const requests = [];
const responses = [responseWithTargets(['R1', 'R2']), responseWithTargets([]), responseWithTargets(['R1'])];
const store = new ConversationStore(async request => {
  requests.push(structuredClone(request));
  return responses.shift();
});

await store.ask('case', '우리 회사, 참여 가능해?', 'QUALIFICATION_SUMMARY', 'QUALIFICATION');
assert.deepEqual(store.get('case').reply.visible_requirement_keys, ['R1', 'R2']);

await store.ask('case', '뭘 더 확인해야 해?', 'REQUIRED_CHECKS', 'QUALIFICATION');
assert.deepEqual(
  store.get('case').reply.visible_requirement_keys,
  ['R1', 'R2'],
  'Non-target turn must preserve the last visible requirement list for the same receipt',
);

await store.ask('case', '첫 번째 조건 근거 보여줘', 'REQUIREMENT_EVIDENCE', 'QUALIFICATION');
assert.equal(requests[2].requirement_key, undefined, 'Explicit ordinal must not reuse UI focus');
assert.deepEqual(requests[2].conversation_context.visible_requirement_keys, ['R1', 'R2']);
assert.deepEqual(requests[2].conversation_context.last_read_receipt, receipt);

console.log('Copilot target memory across non-target turns passed.');
