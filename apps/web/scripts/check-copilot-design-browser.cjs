(async () => {
// Actual app components in Chromium, synthetic API only. No product DB or LLM.
const assert = (await import('node:assert/strict')).default;
const fs = (await import('node:fs')).default;
const path = (await import('node:path')).default;
const vm = (await import('node:vm')).default;
const ts = (await import('typescript')).default;
const { pathToFileURL } = await import('node:url');
const { resolve } = await import('node:path');
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE
  ? pathToFileURL(resolve(process.env.PLAYWRIGHT_MODULE, 'index.mjs')).href : 'playwright');
const root = path.resolve(__dirname, '..');
const cache = new Map();
function load(file) {
  if (cache.has(file)) return cache.get(file).exports;
  const compiled = { exports: {} }; cache.set(file, compiled);
  const js = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInThisContext(`(function(require,module,exports){${js}\n})`, { filename: file })(name => load(path.resolve(path.dirname(file), `${name}.ts`)), compiled, compiled.exports);
  return compiled.exports;
}
  const origin = process.env.COPILOT_UI_URL || 'http://127.0.0.1:3000';
  if (!['127.0.0.1', 'localhost'].includes(new URL(origin).hostname)) throw Error('Loopback UI only');
  const out = process.env.COPILOT_SCREENSHOT_DIR || '/tmp/copilot-design'; fs.mkdirSync(out, { recursive: true });
  const m = load(path.join(root, 'lib/copilot-mocks.ts')).copilotMocks;
  const prov = m.insufficientData.product_state.provenance, id = prov.case_id;
  const req = m.productEvidence.product_state.requirement, e = m.productEvidence.sources[0];
  const company = { id: prov.company_id, name: '합성 검증 회사', industries: [], staff: null, performances: [], certifications: [], company_size: 'SMALL', region_code: null, region_name: null };
  const caseItem = { id, company_id: company.id, notice_id: prov.notice_id, bid_notice_no: 'TEST-COPILOT', notice_title: '합성 공고 · 디자인 검증', title: '통합 검증', status: 'DRAFT', baseline_version_number: 1, current_version_number: 2, documents: [], created_at: '2026-09-11T00:00:00Z' };
  const catalog = { contract_version:'copilot-guided-jobs-v1', jobs:[
    { job_id:'changed_notice', label:'변경 공고 대응', order:1, questions:[
      { question_id:'what_changed', label:'무엇이 바뀌었나요?', order:1, answer_scope:'변경 설명', completion_criteria:['변경 확인'], required_tools:['READ_CHANGES'], availability:'AVAILABLE', unavailable_reason:null },
      { question_id:'company_impact', label:'우리 회사에 어떤 영향이 있나요?', order:2, answer_scope:'회사 영향', completion_criteria:['영향 확인'], required_tools:['READ_CHANGES','READ_JUDGMENT','READ_PROFILE'], availability:'AVAILABLE', unavailable_reason:null },
      { question_id:'next_checks', label:'무엇을 확인해야 하나요?', order:3, answer_scope:'확인사항', completion_criteria:['다음 행동'], required_tools:['READ_CHECKS'], availability:'AVAILABLE', unavailable_reason:null },
    ] },
    { job_id:'bid_preparation', label:'입찰 참여 준비', order:2, questions:[
      { question_id:'documents_deadlines_methods', label:'필요한 서류·기한·방법은?', order:1, answer_scope:'서류', completion_criteria:['서류 확인'], required_tools:['READ_DOCUMENT'], availability:'AVAILABLE', unavailable_reason:null },
      { question_id:'preparation_order', label:'준비 순서는?', order:2, answer_scope:'순서', completion_criteria:['순서 확인'], required_tools:['READ_DOCUMENT'], availability:'AVAILABLE', unavailable_reason:null },
      { question_id:'unresolved', label:'아직 확인하지 못한 것은?', order:3, answer_scope:'미확인', completion_criteria:['미확인 확인'], required_tools:['READ_CHECKS'], availability:'AVAILABLE', unavailable_reason:null },
    ] },
  ] };
  const versions = [1,2].map(n => ({ id: n===2 ? prov.notice_version_id : 'baseline-version', version_number:n, documents:[], is_current:n===2, collected_at:'2026-09-11T00:00:00Z', bid_closed_at:null, estimated_price:null, allocated_budget:null, contract_method:null }));
  let mode = 'summary', authMode='anonymous', logoutMode='ok', saved=false, failWorkspace=false, confirms=0, reads=0;
  const errors=[];
  const summary = () => {
    const p = { ...prov, judgment_run_id: saved?'saved-judgment':prov.judgment_run_id };
    const product = { ...m.insufficientData.product_state, provenance:p };
    return { ...m.productEvidence, intent:'QUALIFICATION_SUMMARY', product_state:product,
      answer:'현재 저장된 판정만으로는 참가 가능 여부를 확정할 수 없습니다. [S1]',
      presentation:{conclusion:'현재 저장된 판정만으로는 참가 가능 여부를 확정할 수 없습니다.', reasons:[
        {text:'정보통신공사업 등록 여부를 확인해 주세요.',requirement_key:req.requirement_key,evidence_refs:['S1']},
        {text:'구조화에서 제외된 요건 — 원문 문구를 확보하지 못했습니다.',requirement_key:null,evidence_refs:[]},
      ],limitations:['판정에 포함되지 않은 확인사항은 참가자격 화면에서 함께 확인해 주세요.'],next_action:{kind:'SELECT_REQUIREMENT',label:'요건과 근거를 확인해 주세요.',requirement_key:null}},
      reply_context:{status:'RESOLVED',requirement_key:null,visible_requirement_keys:[req.requirement_key],last_read_receipt:{kind:'product',provenance:p},context_revision:1,request_id:null} };
  };
  const analysis = n => ({ id:n===2?prov.analysis_run_id:'baseline-analysis',notice_id:prov.notice_id,notice_version_id:versions[n-1].id,version_number:n,status:'SUCCEEDED',requirements:[req],evidence:[e.evidence],diagnostics:[{kind:'NOTICE_FACT',code:'FACT',message:'판정 대상이 아닌 확인사항',evidence_keys:['MISSING']},{kind:'PIPELINE',code:'P',message:'처리 진단'}],dropped_requirements:[{raw:'',reason_code:'MISSING_RAW'}],requirement_count:1,evidence_count:1 });
  const run = baseline => ({ ...summary().product_state, id:baseline?'baseline-judgment':saved?'saved-judgment':prov.judgment_run_id,preflight_case_id:id,company_id:prov.company_id,notice_version_id:baseline?versions[0].id:prov.notice_version_id,analysis_run_id:baseline?'baseline-analysis':prov.analysis_run_id,rule_version:prov.rule_version,profile_snapshot:{},profile_completeness:{} });
  const launchOptions = process.env.COPILOT_BROWSER_CHANNEL
    ? {headless:true,channel:process.env.COPILOT_BROWSER_CHANNEL} : {headless:true};
  const browser = await chromium.launch(launchOptions);
  let page;
  try {
    page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror',err=>errors.push(err.message));
    await page.route('**/api/v1/**',async route=>{
      const request=route.request(), url=new URL(request.url()), p=url.pathname;
      const headers={'access-control-allow-origin':origin,'access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type','access-control-allow-methods':'GET,POST,OPTIONS'};
      const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',headers,body:JSON.stringify(body)});
      if(request.method()==='OPTIONS') return route.fulfill({status:204,headers});
      if(p==='/api/v1/auth/me'){
        if(authMode==='unauthorized')return reply({error:{code:'AUTHENTICATION_REQUIRED',message:'로그인이 필요합니다.'}},401);
        if(authMode==='error')return reply({error:{code:'AUTH_STATUS_FAILED',message:'인증 서버를 확인하지 못했습니다.'}},503);
        if(authMode==='authenticated')return reply({id:'test-user',username:'golden-j01',role:'USER',company_id:company.id,company_name:company.name});
        return reply(null);
      }
      if(p==='/api/v1/auth/logout'){
        if(logoutMode==='error')return reply({error:{code:'LOGOUT_FAILED',message:'세션 해제에 실패했습니다.'}},503);
        return route.fulfill({status:204,headers});
      }
      if(p.endsWith('/copilot/actions/confirm')){
        confirms++;const action=request.postDataJSON().action;assert.equal(action.user_input.evidence_held,false);saved=true;failWorkspace=true;
        return reply({id:'answer',preflight_case_id:id,result_judgment_run_id:'saved-judgment',result:run(false)});
      }
      if(p.endsWith('/copilot/jobs'))return reply(catalog);
      if(p.endsWith('/copilot/chat')){
        reads++; const body=request.postDataJSON();
        if(mode==='loading') await new Promise(resolve=>setTimeout(resolve,1200));
        if(mode==='no-judgment')return reply({error:{code:'CURRENT_JUDGMENT_REQUIRED',message:'판정 필요'}},409);
        if(mode==='error')return reply({error:{code:'TEST_READ_FAILED',message:'연결을 확인하지 못했습니다.'}},503);
        if(mode==='no-evidence')return reply({...m.noEvidence,presentation:{conclusion:'검색된 공고문 근거가 없습니다.',reasons:[],limitations:['조건이 없다는 뜻은 아닙니다.'],next_action:null}});
        if(body.intent==='ACTION_REQUEST')return reply({...m.answerProposal,actions:[{...m.answerProposal.actions[0],user_input:body.user_input}]});
        if(body.intent==='REQUIRED_CHECKS'||body.question_id==='next_checks')return reply({...m.askableUnknown,reply_context:summary().reply_context});
        if(body.intent==='REQUIREMENT_EVIDENCE')return reply({...m.productEvidence,reply_context:summary().reply_context});
        if(body.intent==='CHANGED_NOTICE'||body.question_id==='what_changed')return reply({...m.revalidationProposal,actions:[],presentation:{conclusion:'공고 1차와 2차의 분석된 요건을 비교했습니다.',reasons:[],limitations:['공고 전체의 모든 변경을 확인했다는 의미는 아닙니다.'],next_action:null}});
        return reply(summary());
      }
      if(failWorkspace && p===`/api/v1/preflight-cases/${id}`)return reply({error:{code:'WORKSPACE_REFRESH_FAILED',message:'화면 갱신 실패'}},503);
      if(p==='/api/v1/companies')return reply([company]);
      if(p==='/api/v1/preflight-cases')return reply({items:[caseItem],total:1,limit:100,offset:0});
      if(p.endsWith('/qualification-questions'))return reply(m.askableUnknown.product_state.questions);
      if(p.endsWith('/qualification-judgment-runs'))return reply([run(false),run(true)]);
      if(p.includes('/qualification-judgment-runs/'))return reply(run(p.endsWith('baseline-judgment')));
      if(p.includes('/qualification-analyses/'))return reply(analysis(p.endsWith('baseline-analysis')?1:2));
      if(p.endsWith('/qualification-analyses'))return reply([analysis(p.includes('/versions/1/')?1:2)]);
      if(p===`/api/v1/preflight-cases/${id}`)return reply(caseItem);
      if(p.endsWith('/versions'))return reply(versions);
      if(p==='/api/v1/notices')return reply({items:[{id:prov.notice_id,bid_notice_no:'TEST-COPILOT',title:caseItem.notice_title}],total:1});
      if(p===`/api/v1/notices/${prov.notice_id}`)return reply({id:prov.notice_id,title:caseItem.notice_title,latest:versions[1]});
      return reply({error:{code:'UNEXPECTED_TEST_ROUTE',message:p}},404);
    });
    const open = async()=>{
      await page.goto(`${origin}/qualification?caseId=${id}`);
      // The SSR launcher exists before hydration. Wait for client-loaded case
      // data, rather than clicking an inert server-rendered button.
      await page.getByRole('heading',{name:caseItem.notice_title,exact:true}).waitFor();
      await page.getByRole('button',{name:'AI Copilot',exact:true}).click();
      await page.locator('#copilot-panel[open]').waitFor();
    };
    const waitForCopilotAfterNavigation = async()=>{
      await page.locator('#copilot-panel[open]').waitFor();
    };
    const shoot=async name=>page.locator('#copilot-panel').screenshot({path:path.join(out,`${name}.png`)});
    await open();await shoot('01-empty');assert.equal(await page.locator('.copilot-mascot').count(),3);
    await page.getByRole('button',{name:'2. 우리 회사에 어떤 영향이 있나요?',exact:true}).click();
    await page.locator('[data-state=ANSWER]').waitFor();await shoot('04-answer');
    assert.equal(await page.locator('.copilot-header-badges').getByText('조회 v2',{exact:true}).count(),1);
    assert.equal(await page.locator('.copilot-header-badges').getByText('확인 필요',{exact:true}).count(),1);
    await page.locator('.copilot-evidence-chip').first().click();await page.waitForURL('**/evidence?**');
    await waitForCopilotAfterNavigation();
    await page.locator('.copilot-conclusion').waitFor();
    assert.equal(await page.getByRole('button',{name:'1. 무엇이 바뀌었나요?',exact:true}).count(),1,'Evidence page should restore the guided question catalog');
    await page.goto(`${origin}/changes?caseId=${id}`);
    await page.getByRole('heading',{name:caseItem.notice_title,exact:true}).waitFor();
    await page.getByRole('button',{name:'AI Copilot',exact:true}).click();
    await page.locator('#copilot-panel[open]').waitFor();
    await page.getByRole('button',{name:'1. 무엇이 바뀌었나요?',exact:true}).click();await page.locator('[data-state=CHANGED_NOTICE]').waitFor();await shoot('05-changed');
    await page.getByRole('link',{name:'변경사항 상세 보기 · 06'}).click();await page.waitForURL('**/changes?**');
    await waitForCopilotAfterNavigation();
    await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector('#copilot-panel').matches(':modal'));
    await shoot('08-mobile');assert((await page.locator('#copilot-panel').boundingBox()).width<=390);
    await page.setViewportSize({width:1440,height:1000});
    for(const [testMode,state,file] of [['no-judgment','NO_JUDGMENT','02-no-judgment'],['no-evidence','INSUFFICIENT_EVIDENCE','06-no-evidence'],['error','ERROR','07-error']]){
      mode=testMode;await open();await page.getByRole('button',{name:'2. 우리 회사에 어떤 영향이 있나요?',exact:true}).click();await page.locator(`[data-state=${state}]`).waitFor();await shoot(file);
      if(state==='INSUFFICIENT_EVIDENCE')assert(await page.getByRole('link',{name:'근거 원문 직접 확인'}).isVisible());
    }
    mode='loading';await open();await page.getByRole('button',{name:'2. 우리 회사에 어떤 영향이 있나요?',exact:true}).click();await page.locator('[data-state=LOADING]').waitFor();await shoot('03-loading');await page.locator('[data-state=ANSWER]').waitFor();
    assert.equal(confirms,0,'Every read/design state performs zero confirms');
    mode='summary';await open();await page.getByRole('button',{name:'3. 무엇을 확인해야 하나요?',exact:true}).click();await page.locator('[data-state=NEEDS_CHECK]').waitFor();
    await page.locator('#copilot-panel').getByRole('button',{name:/· 답변 입력$/}).click();await page.waitForURL('**/ask-back?**');
    await waitForCopilotAfterNavigation();
    assert.equal(await page.locator('#copilot-panel').getByRole('button',{name:'내용 확인 후 실행'}).count(),0,'Panel summarizes, detail confirms');
    await page.getByRole('button',{name:'도우미 닫기'}).click();
    const card=page.locator('.app-shell-content .copilot-action-card').first();
    await card.getByLabel('이 요건을 충족하나요?').selectOption('true');await card.getByLabel('증빙을 보유하고 있나요?').selectOption('false');
    await card.getByRole('button',{name:'반영 제안 받기 · 아직 저장 안 함'}).click();await card.getByRole('button',{name:'내용 확인 후 실행'}).click();
    await card.getByText('반영 후 새 판정 결과를 확인했습니다.',{exact:true}).waitFor();
    await page.getByText('작업 상태는 위에 유지됩니다.',{exact:false}).waitFor();assert.equal(confirms,1);
    await page.locator(`.app-shell-content a[href="/qualification?caseId=${id}"]`).first().click();
    await page.waitForURL('**/qualification?**');
    await page.locator('.app-shell-content .copilot-action-card').getByText('반영 후 새 판정 결과를 확인했습니다.',{exact:true}).waitFor();
    await page.getByRole('button',{name:'화면 정보 다시 조회'}).waitFor();
    failWorkspace=false;await page.getByRole('button',{name:'화면 정보 다시 조회'}).click();assert.equal(confirms,1);
    await page.goto(`${origin}/evidence?caseId=${id}&evidence=E1&analysisRunId=historical-analysis`);
    await page.getByRole('heading',{name:'이 근거는 이전 분석 기준입니다'}).waitFor();
    assert.equal(await page.locator('.app-shell-content blockquote').count(),0);
    await page.goto(`${origin}/evaluation?caseId=${id}`);assert.equal(await page.getByRole('button',{name:'AI Copilot',exact:true}).count(),0);
    authMode='error';await page.goto(`${origin}/notices`);
    await page.getByRole('heading',{name:'로그인 상태를 확인하지 못했습니다.',exact:true}).waitFor();
    assert.equal(new URL(page.url()).pathname,'/notices','5xx must not masquerade as logout');
    authMode='unauthorized';await page.goto(`${origin}/notices`);await page.waitForURL('**/login');
    authMode='authenticated';logoutMode='error';await page.goto(`${origin}/notices`);
    await page.getByText(company.name,{exact:true}).first().waitFor();
    await page.getByRole('button',{name:'로그아웃',exact:true}).first().click();
    await page.getByRole('alert').getByText(/로그아웃을 완료하지 못했습니다/).waitFor();
    assert.equal(new URL(page.url()).pathname,'/notices','failed logout must keep the current session UI');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'browser-result.json'),JSON.stringify({result:'passed',sevenStates:true,mobile:true,confirmRequests:confirms,readRequests:reads,pageErrors:errors,mode:'actual UI + synthetic intercepted API, not real DB browser E2E'},null,2));
    console.log('PASS 7 display states, mascot, badges, source/detail navigation, Drawer, explicit detail confirm and workspace refresh failure');
  } catch (error) {
    if (page) {
      await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});
      fs.writeFileSync(path.join(out,'failure.html'),await page.content().catch(()=>''));
    }
    fs.writeFileSync(path.join(out,'browser-failure.json'),JSON.stringify({error:String(error),pageErrors:errors},null,2));
    throw error;
  } finally{await browser.close();}
})().catch(err=>{console.error(err);process.exitCode=1;});
