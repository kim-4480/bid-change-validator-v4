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


const { ActionController } = load(resolve(root, 'lib/copilot-actions.ts'));
const { ApiError } = load(resolve(root, 'lib/api.ts'));
const { copilotMocks: m } = load(resolve(root, 'lib/copilot-mocks.ts'));
const action = m.answerProposal.actions[0], id = action.expected.case_id;
const receipt = { kind: 'product', provenance: action.expected };
const checks = { ...m.askableUnknown, reply_context: { status: 'RESOLVED', last_read_receipt: receipt } };
const saved = { preflight_case_id: id, result_judgment_run_id: 'new', result: { id: 'new' } };
const fresh = { ...m.eligible, product_state: { ...m.eligible.product_state, provenance: { ...action.expected, judgment_run_id: 'new' } } };
let writes = 0, finish;
const reads = [];
const states = [];
const c = new ActionController(async r => {
 reads.push(r);
 if (r.intent === 'REQUIRED_CHECKS') return checks;
 if (r.intent === 'ACTION_REQUEST') return { ...m.answerProposal, actions: [{ ...action, user_input: r.user_input }] };
 return fresh;
}, async () => { writes++; return new Promise(resolve => { finish = resolve; }); });
c.subscribe(() => states.push(c.get(id).stage));
await c.beginAnswer(id, action.requirement_key);
assert.equal(c.get(id).draft.satisfies_requirement, null);
assert.equal(c.get(id).draft.evidence_held, null);
await c.propose(id);
assert.equal(reads.length, 1, 'null never becomes false');
c.edit(id, { satisfies_requirement: false, evidence_held: false });
await c.propose(id);
assert.equal(c.get(id).proposal.user_input.satisfies_requirement, false);
assert.equal(c.get(id).proposal.user_input.evidence_held, false);
c.edit(id, { normalized_value: 'changed' });
assert.equal(c.get(id).proposal, null, 'editing invalidates proposal');
await c.confirm(id, true); assert.equal(writes, 0);
await c.propose(id);
await c.confirm(id, false); assert.equal(writes, 0);
const pending = c.confirm(id, true);
await c.confirm(id, true); assert.equal(writes, 1, 'synchronous double click lock');
c.edit(id, { satisfies_requirement: true });
assert.equal(c.get(id).draft.satisfies_requirement, false);
finish(saved); await pending;
assert.equal(c.get(id).stage, 'COMPLETED');
assert(states.includes('CONFIRMING') && states.includes('REFRESHING'));
await c.confirm(id, true); assert.equal(writes, 1, 'consumed proposal cannot replay');
assert.equal(c.get('other-case').stage, 'IDLE');
console.log('PASS null/false, edit invalidation, explicit confirm, duplicate/replay and refresh lifecycle');

for (const [error, expected] of [[new Error('timeout'), 'OUTCOME_UNKNOWN'], [new ApiError('server', 500, 'ERROR'), 'OUTCOME_UNKNOWN'], [new ApiError('stale',409,'STALE_ACTION_CONTEXT'),'STALE']]) {
 let n=0;
 const x = new ActionController(async()=>fresh,async()=>{n++;throw error;});
 x.adopt(id, action); await x.confirm(id,true);
 assert.equal(x.get(id).stage, expected);
 await x.confirm(id,true); assert.equal(n,1);
 if(expected==='OUTCOME_UNKNOWN'){
   await x.refresh(id); assert.equal(x.get(id).stage,'OUTCOME_UNKNOWN','read cannot prove prior success');
   x.cancel(id); assert.equal(x.get(id).stage,'OUTCOME_UNKNOWN');
   x.adopt(id,action); assert.equal(x.get(id).proposal,null);
 }
}
let refreshFails=true;
const y=new ActionController(async()=>{if(refreshFails)throw Error('read failed');return fresh;},async()=>saved);
y.adopt(id,action); await y.confirm(id,true);
assert.equal(y.get(id).stage,'DONE_REFRESH_FAILED');
refreshFails=false; await y.refresh(id); assert.equal(y.get(id).stage,'COMPLETED');
console.log('PASS unknown outcome, no retry, confirmed save + failed refresh, read-only recovery');

const blocked=new ActionController(async()=>({...checks,product_state:m.nonAskableUnknown.product_state}));
await blocked.beginAnswer(id,action.requirement_key); assert.equal(blocked.get(id).stage,'FAILED');
const stale=new ActionController(async()=>checks);
await stale.beginAnswer(id,action.requirement_key,'old');assert.equal(stale.get(id).stage,'STALE');
const cross=new ActionController();
cross.adopt('other',action); assert.equal(cross.get('other').proposal,null);
const reval=new ActionController(async()=>m.revalidationProposal);
await reval.propose(id,true); assert.equal(reval.get(id).proposal.action_type,'REVALIDATE');
console.log('PASS askability, stale viewed judgment, cross-case adoption, whole-scope revalidation');
