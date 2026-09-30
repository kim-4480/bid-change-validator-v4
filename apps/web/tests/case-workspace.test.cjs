/* oxlint-disable typescript/no-require-imports -- Standalone Node CommonJS test runner. */
// Run: node --test apps/web/tests/case-workspace.test.cjs (no browser or new dependencies).
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');

function workspaceModule({ stale = false, noCurrent = false, missingVersion = false, ruleVersion = 'qualification-rules-v0.3', mixedRules = false } = {}) {
  const calls = [];
  const caseItem = { id: 'case', notice_id: 'notice', company_id: 'company', baseline_version_number: 1, current_version_number: 2 };
  const baseline = { id: 'a1', notice_version_id: 'v1', status: 'SUCCEEDED' };
  const current = { id: 'a2', notice_version_id: 'v2', status: 'SUCCEEDED' };
  const j1 = { id: 'j1', analysis_run_id: 'a1', notice_version_id: 'v1', company_id: 'company', rule_version: ruleVersion };
  const j2 = { id: 'j2', analysis_run_id: stale ? 'old' : 'a2', notice_version_id: 'v2', company_id: 'company', rule_version: ruleVersion };
  const staleRule = { id: 'j-stale-rule', analysis_run_id: 'a2', notice_version_id: 'v2', company_id: 'company', rule_version: 'qualification-rules-v0.2' };
  const mocks = {
    getPreflightCase: async (id) => { if (id !== 'case') throw new Error('not found'); return caseItem; },
    getNotice: async () => ({ latest: { id: 'v3' } }),
    getNoticeVersions: async () => missingVersion ? [] : [{ id: 'v1', version_number: 1 }, { id: 'v2', version_number: 2 }],
    listCompanies: async () => [{ id: 'company' }],
    listQualificationAnalyses: async (_, version) => [version === 1 ? baseline : current],
    getQualificationAnalysis: async (id) => ({ id, requirements: [], evidence: [] }),
    listQualificationJudgments: async () => noCurrent ? [j1] : mixedRules ? [staleRule, j2, j1] : [j2, j1],
    getQualificationJudgment: async (id) => id === 'j1' ? j1 : id === 'j-stale-rule' ? staleRule : j2,
    listQualificationQuestions: async (_, id) => { calls.push(id); return []; },
  };
  const source = fs.readFileSync(path.join(__dirname, '../lib/case-workspace.ts'), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const mod = { exports: {} };
  vm.runInNewContext(code, { require: (name) => name === 'react' ? require('react') : mocks, exports: mod.exports, module: mod });
  return { ...mod.exports, calls };
}

test('current questions and evidence use the current judgment; baseline is only the diff source', async () => {
  const workspaceApi = workspaceModule();
  const w = await workspaceApi.loadCaseWorkspace('case');
  assert.equal(w.sourceJudgment.id, 'j1');
  assert.equal(w.displayJudgment.analysis_run_id, w.currentAnalysis.id);
  assert.deepEqual(workspaceApi.calls, ['j2']);
});

test('previous rule judgments are not displayed or used as question sources', async () => {
  const workspaceApi = workspaceModule({ ruleVersion: 'qualification-rules-v0.2' });
  const w = await workspaceApi.loadCaseWorkspace('case');
  assert.equal(w.sourceJudgment, null);
  assert.equal(w.displayJudgment, null);
  assert.deepEqual(workspaceApi.calls, []);
});

test('mixed previous/current rule summaries select the current rule judgment', async () => {
  const workspaceApi = workspaceModule({ mixedRules: true });
  const w = await workspaceApi.loadCaseWorkspace('case');
  assert.equal(w.displayJudgment.id, 'j2');
  assert.equal(w.displayJudgment.rule_version, 'qualification-rules-v0.3');
  assert.deepEqual(workspaceApi.calls, ['j2']);
});

test('summary matching skips previous rule results before selecting a judgment', () => {
  const workspaceApi = workspaceModule();
  const analysis = { id: 'a2', notice_version_id: 'v2', status: 'SUCCEEDED' };
  const base = { analysis_run_id: 'a2', notice_version_id: 'v2', company_id: 'company' };
  assert.equal(workspaceApi.judgmentMatchesAnalysis({ ...base, rule_version: 'qualification-rules-v0.2' }, analysis, 'company'), false);
  assert.equal(workspaceApi.judgmentMatchesAnalysis({ ...base, rule_version: 'qualification-rules-v0.3' }, analysis, 'company'), true);
});

test('reanalysis or missing current judgment never falls back to a baseline/old result', async () => {
  for (const scenario of [{ stale: true }, { noCurrent: true }]) {
    const workspaceApi = workspaceModule(scenario);
    const w = await workspaceApi.loadCaseWorkspace('case');
    assert.equal(w.displayJudgment, null);
    assert.deepEqual(workspaceApi.calls, []);
  }
});

test('invalid case or missing pinned version fails instead of opening another case/version', async () => {
  await assert.rejects(workspaceModule().loadCaseWorkspace('invalid'), /not found/);
  await assert.rejects(workspaceModule({ missingVersion: true }).loadCaseWorkspace('case'));
});
