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

const { ActionController, currentRevalidation } = load(resolve(root, 'lib/copilot-actions.ts'));
const { ConversationStore, inferE1Intent, isCopilotHelpQuestion, copilotReadErrorMessage } = load(resolve(root, 'lib/copilot-conversation.ts'));
const { ApiError, apiFetch } = load(resolve(root, 'lib/api.ts'));
const { copilotMocks: m } = load(resolve(root, 'lib/copilot-mocks.ts'));
const action = m.answerProposal.actions[0], id = action.expected.case_id;

for (const [code, stage] of [['AUTHENTICATION_REQUIRED','AUTH_REQUIRED'],['INVALID_SESSION','AUTH_REQUIRED'],['UNKNOWN_PROXY','OUTCOME_UNKNOWN']]) {
  let writes=0;
  const c = new ActionController(async()=>m.eligible,async()=>{writes++;throw new ApiError('auth',401,code);});
  c.adopt(id,action);await c.confirm(id,true);assert.equal(c.get(id).stage,stage);
  await c.confirm(id,true);assert.equal(writes,1);
  c.cancel(id);assert.equal(c.get(id).stage,stage==='AUTH_REQUIRED'?'IDLE':'OUTCOME_UNKNOWN');
}

const c=new ActionController();c.adopt(id,action);assert(c.acquireReview(id));
assert.equal(c.get(id).proposal,null);assert.equal(c.acquireReview(id),false);
c.adopt(id,action);assert.equal(c.get(id).proposal,null);c.releaseReview(id);c.adopt(id,action);assert(c.get(id).proposal);
const result={preflight_case_id:id,baseline_analysis_run_id:'a1',current_analysis_run_id:'a2',result_judgment_run_id:'j2',revalidated_keys:[]};
assert.equal(currentRevalidation(result,{caseId:id,baselineAnalysisId:'a1',currentAnalysisId:'a2',judgmentId:'j2'}),result);
for(const patch of [{caseId:'other'},{baselineAnalysisId:'other'},{currentAnalysisId:'a3'},{judgmentId:'j3'}])
 assert.equal(currentRevalidation(result,{caseId:id,baselineAnalysisId:'a1',currentAnalysisId:'a2',judgmentId:'j2',...patch}),null);

// Failed reads retry in-place: no duplicate user turn, same intent, new request id.
let tries=0;const requests=[];const store=new ConversationStore(async request=>{requests.push(request);if(!tries++)throw Error('offline');return m.eligible;});
await store.ask(id,'변경된 요건 보여줘','CHANGED_NOTICE','CHANGES');
assert.equal(store.get(id).turns.length,1);
await store.retry(id);
assert.equal(store.get(id).turns.length,1);
assert.equal(store.get(id).turns[0].question,'변경된 요건 보여줘');
assert.equal(requests[1].message,requests[0].message);assert.equal(requests[1].intent,'CHANGED_NOTICE');
assert.notEqual(requests[1].conversation_context.request_id,requests[0].conversation_context.request_id);
assert.deepEqual(requests[1].conversation_context.last_read_receipt,requests[0].conversation_context.last_read_receipt);

// E1 help is answered locally and therefore cannot cause a read or write.
assert(isCopilotHelpQuestion('내가 물어볼 수 있는 질문이 뭐야?'));
assert(isCopilotHelpQuestion('그중에서 지금 할 수 있는 것부터 알려줘.'));
let helpReads=0;
const helpStore=new ConversationStore(async()=>{helpReads++;return m.eligible;});
await helpStore.ask(id,'내가 물어볼 수 있는 질문이 뭐야?');
assert.equal(helpReads,0);
assert.equal(helpStore.get(id).turns.length,1);
assert.match(helpStore.get(id).turns[0].response.presentation.conclusion,/참가자격 결과/);

// E1 aliases are intentionally bounded. Product questions need a company subject;
// a document statement such as '중소기업만 참가할 수 있다는 뜻이야?' remains for E2/RAG.
assert.equal(inferE1Intent('우리 회사가 이 공고에 참가할 수 있는지 알려줘'),'QUALIFICATION_SUMMARY');
assert.equal(inferE1Intent('이거 우리도 넣어도 돼?'),'QUALIFICATION_SUMMARY');
assert.equal(inferE1Intent('이전 공고에서 무엇이 바뀌었는지 알려줘'),'CHANGED_NOTICE');
assert.equal(inferE1Intent('공고 자체가 바뀐 내용만 보여줘'),'CHANGED_NOTICE');
assert.equal(inferE1Intent('중소기업만 참가할 수 있다는 뜻이야?'),undefined);

const aliased=[];const aliasStore=new ConversationStore(async request=>{aliased.push(request);return m.eligible;});
await aliasStore.ask(id,'우리 회사가 이 공고에 참가할 수 있는지 알려줘');
assert.equal(aliased[0].intent,'QUALIFICATION_SUMMARY');

// Common read failures should explain the cause rather than exposing backend wording.
for (const [code, pattern] of [
  ['CHANGED_NOTICE_REQUIRED', /이전 버전과 회사 기준/],
  ['QUALIFICATION_ANALYSIS_REQUIRED', /분석이 준비되지 않은/],
  ['BASELINE_JUDGMENT_REQUIRED', /이전 버전 기준의 회사 판정/],
  ['QUALIFICATION_ANALYSIS_FAILED', /공고 분석이 완료되지/],
  ['STALE_ACTION_CONTEXT', /기준이 바뀌었습니다/],
]) {
  assert.match(copilotReadErrorMessage(new ApiError('raw backend message',409,code)),pattern);
}
assert.equal(copilotReadErrorMessage(new ApiError('fallback',500,'OTHER')),'fallback');

const fetches=[],originalFetch=globalThis.fetch;
try{globalThis.fetch=async(url,init)=>{fetches.push([url,init]);return {};};
 await apiFetch('/api/v1/copilot/chat',{method:'POST',body:'{}'});
 await apiFetch('https://unrelated.invalid/document');
 assert.equal(fetches[0][1].credentials,'include');assert.equal(fetches[1][1].credentials,'omit');
 assert.equal(fetches.length,2);
}finally{globalThis.fetch=originalFetch;}
console.log('PASS auth/write safety, shared review lock, provenance, in-place retry, E1 local help, bounded aliases, read error guidance, API-origin cookie boundary');