'use client';

import { usePathname, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, Send, X } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CopilotNavigationLink } from './navigation-link';
import { CopilotMascot } from './mascot';
import { EnvelopeAnswer } from './envelope-answer';
import { useActions, useCopilot, useCopilotNavigation } from './provider';
import { isLocked } from '@/lib/copilot-actions';
import { getCopilotStatusLabel, getSourceLocationLabel } from '@/lib/copilot-view-model';
import { getCopilotJobs } from '@/lib/copilot-api';
import type { CopilotChatResponse, CopilotIntent, CopilotSource, GuidedJobCatalog } from '@/lib/copilot-api';
import './panel.css';

const pages = { '/qualification': 'QUALIFICATION', '/ask-back': 'ASK_BACK', '/evidence': 'EVIDENCE', '/changes': 'CHANGES' } as const;
const noJudgmentCodes = ['CURRENT_JUDGMENT_REQUIRED', 'QUALIFICATION_JUDGMENT_NOT_FOUND', 'JUDGMENT_NOT_FOUND'];
const href = (page: string, caseId: string) => `${page}?caseId=${encodeURIComponent(caseId)}`;

export function CopilotPanel() {
  const pathname = usePathname();
  const caseId = useSearchParams().get('caseId') ?? '';
  const [open, setOpen] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const page = pages[pathname as keyof typeof pages];
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    const media = window.matchMedia('(min-width: 1024px)');
    const display = () => {
      element.close();
      if (open && page) { if (media.matches) element.show(); else element.showModal(); }
    };
    display();
    media.addEventListener('change', display);
    return () => { media.removeEventListener('change', display); element.close(); };
  }, [open, page]);
  const close = () => { setOpen(false); toggle.current?.focus(); };
  if (!page) return null;
  return <>
    <button type="button" ref={toggle} className="copilot-launch" aria-expanded={open} aria-controls="copilot-panel" onClick={() => setOpen(value => !value)}>
      <CopilotMascot /> AI Copilot
    </button>
    <dialog ref={dialog} id="copilot-panel" className="copilot-panel" aria-labelledby="copilot-title" onCancel={close}>
      <PanelHeader caseId={caseId} close={close} />
      <PanelBody key={caseId} caseId={caseId} page={page} />
    </dialog>
  </>;
}

function PanelHeader({ caseId, close }: { caseId: string; close: () => void }) {
  const { store, state } = useCopilot(caseId);
  const last = [...state.turns].reverse().find(turn => turn.response?.product_state)?.response?.product_state;
  const summary = last && 'overall_status' in last ? last : null;
  const version = last && ('version_number' in last.provenance ? last.provenance.version_number : last.provenance.current.version_number);
  return <header className="copilot-header">
    <CopilotMascot /><h2 id="copilot-title">AI Copilot</h2>
    <div className="copilot-header-badges" aria-label="최근 조회한 판정 기준">
      {version != null && <span className="copilot-badge">조회 v{version}</span>}
      {summary && !state.error && <span className={`copilot-badge copilot-status-${summary.overall_status}`}>{getCopilotStatusLabel(summary.overall_status)}</span>}
    </div>
    {caseId && state.turns.length > 0 && <button type="button" className="copilot-new-conversation"
      disabled={state.busy} onClick={() => store.newConversation(caseId)}>새 대화</button>}
    <button type="button" className="copilot-close" aria-label="도우미 닫기" onClick={close}><X size={18} /></button>
  </header>;
}

function PanelBody({ caseId, page }: { caseId: string; page: typeof pages[keyof typeof pages] }) {
  const { store, state } = useCopilot(caseId);
  const [question, setQuestion] = useState('');
  const [semanticProcessing, setSemanticProcessing] = useState(false);
  const [documentProcessing, setDocumentProcessing] = useState(false);
  const [jobsOpen, setJobsOpen] = useState(true);
  const [catalogState, setCatalogState] = useState<{ caseId: string; catalog: GuidedJobCatalog | null; error: string }>({ caseId: '', catalog: null, error: '' });
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [state.turns, state.busy]);
  useEffect(() => {
    if (!caseId) return;
    const controller = new AbortController();
    void getCopilotJobs(caseId, controller.signal)
      .then(catalog => setCatalogState({ caseId, catalog, error: '' }))
      .catch(error => { if (!controller.signal.aborted) setCatalogState({ caseId, catalog: null, error: error instanceof Error ? error.message : '질문 목록을 불러오지 못했습니다.' }); });
    return () => controller.abort();
  }, [caseId]);
  const catalog = catalogState.caseId === caseId ? catalogState.catalog : null;
  const catalogError = catalogState.caseId === caseId ? catalogState.error : '';
  const ask = (text: string, intent?: CopilotIntent, guided?: { jobId: string; questionId: string }) => {
    if (!caseId || state.busy || !text.trim()) return;
    setJobsOpen(false);
    void store.ask(caseId, text.trim(), intent, page, semanticProcessing, documentProcessing, guided);
  };
  const noJudgment = noJudgmentCodes.includes(state.errorCode);
  const empty = !state.turns.length;
  const jobsExpanded = jobsOpen;
  return <>
    <div className={`copilot-content${empty ? ' copilot-content-empty' : ''}`}>
      {empty && <div className="copilot-empty" data-state="EMPTY">
        <CopilotMascot size={64} />
        <h3>{caseId ? '확인할 업무를 선택해 주세요' : '검토할 공고를 먼저 선택해 주세요'}</h3>
        <p>검증된 질문 순서에 따라 저장된 결과와 공고문 근거를 설명해 드려요.</p>
      </div>}
      {caseId && <div className="copilot-processing-options" aria-label="AI 처리 옵션">
        <label className="copilot-semantic-toggle" htmlFor="copilot-semantic-processing" aria-label="AI 상세 설명 사용">
          <input id="copilot-semantic-processing" type="checkbox" checked={semanticProcessing} disabled={state.busy}
            onChange={event => setSemanticProcessing(event.target.checked)} />
          <span><strong>AI 상세 설명 사용</strong><small>켜면 질문·관련 대화·현재 판정 결과·요건 상태와 판정에 필요한 회사 프로필 정보를 AI 처리에 사용합니다. AI는 참가 가능 여부를 새로 판정하거나 저장하지 않습니다. 대화는 서버 재시작 시 초기화됩니다.</small></span>
        </label>
        <label className="copilot-semantic-toggle" htmlFor="copilot-document-processing" aria-label="공고문 근거 답변 사용">
          <input id="copilot-document-processing" type="checkbox" checked={documentProcessing} disabled={state.busy}
            onChange={event => setDocumentProcessing(event.target.checked)} />
          <span><strong>공고문 근거 답변 사용</strong><small>켜면 질문과 현재 공개 공고문을 외부 AI·임베딩 처리에 사용해 근거 답변을 생성합니다. 회사 프로필·저장 입력은 문서 검색 경로에 보내지 않습니다.</small></span>
        </label>
      </div>}
      {caseId && catalog && <section className="copilot-jobs" aria-label="검증된 업무 질문">
        <button type="button" className="copilot-jobs-toggle" aria-expanded={jobsExpanded} onClick={() => setJobsOpen(value => !value)}>
          <span><ChevronDown size={16} aria-hidden="true" />추천 질문 6개</span>
          <span>{jobsExpanded ? '접기' : '보기'}</span>
        </button>
        {jobsExpanded && <div className="copilot-jobs-list">{catalog.jobs.map(job => <section className="copilot-job" key={job.job_id}>
          <h4>{job.label}</h4>
          <ol>{job.questions.map(item => <li key={item.question_id}>
            <Button type="button" variant="ghost" className="copilot-quiet"
              disabled={state.busy || item.availability === 'BLOCKED'}
              title={item.unavailable_reason ?? item.answer_scope}
              onClick={() => { store.focus(caseId, null); ask(item.label, undefined, { jobId: job.job_id, questionId: item.question_id }); }}>
              {item.order}. {item.label}
            </Button>
            {item.unavailable_reason && <small>{item.unavailable_reason}</small>}
          </li>)}</ol>
        </section>)}</div>}
      </section>}
      {caseId && !catalog && !catalogError && <p className="copilot-limitation">검증된 질문을 확인하고 있어요…</p>}
      {catalogError && <p role="alert" className="copilot-error">{catalogError}</p>}
      {state.focus && <button type="button" className="copilot-focus" onClick={() => store.focus(caseId, null)}>선택한 요건 해제 · 전체 보기</button>}
      <div role="log" aria-label="공고 도우미 대화" aria-live="polite">
        {state.turns.map(turn => {
          const guided = turn.response?.envelope?.guided;
          const job = guided && catalog?.jobs.find(item => item.job_id === guided.job_id);
          const current = guided && job?.questions.find(item => item.question_id === guided.question_id);
          const followUps = current ? job?.questions.filter(item => item.order > current.order && item.availability === 'AVAILABLE').slice(0, 2) ?? [] : [];
          return <div key={turn.id} className="copilot-turn">
            <p className="copilot-question">{turn.question}</p>
            {turn.response && <Answer response={turn.response} caseId={caseId} onSelect={key => {
              store.focus(caseId, key, turn.response?.reply_context);
              ask('그 조건 근거 보여줘', 'REQUIREMENT_EVIDENCE');
            }} />}
            {followUps.length > 0 && <div className="copilot-followups" aria-label="관련 후속 질문">
              <strong>이어서 확인하기</strong>
              {followUps.map(item => <Button type="button" variant="outline" className="copilot-quiet" key={item.question_id}
                disabled={state.busy} onClick={() => ask(item.label, undefined, { jobId: job!.job_id, questionId: item.question_id })}>
                {item.label}
              </Button>)}
            </div>}
          </div>;
        })}
      </div>
      {state.busy && <div className="copilot-answer copilot-loading" data-state="LOADING">
        <output>{documentProcessing ? '공고문 근거를 확인하고 있어요…' : semanticProcessing ? '판정 결과를 이해하기 쉽게 정리하고 있어요…' : '현재 검토 결과를 확인하고 있어요…'}</output>
        <div className="copilot-skeleton" aria-hidden="true"><span /><span /><span /></div>
      </div>}
      {state.error && <div role="alert" className={noJudgment ? 'copilot-notice' : 'copilot-error'} data-state={noJudgment ? 'NO_JUDGMENT' : 'ERROR'}>
        <strong>{noJudgment ? '저장된 판정이 아직 없습니다' : '요청을 완료하지 못했습니다'}</strong>
        <p>{noJudgment ? '참가자격 화면에서 검토 상태를 확인해 주세요. 화면 이동만으로 분석이나 저장을 시작하지 않습니다.' : state.error}</p>
        {caseId && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={href('/qualification', caseId)}>참가자격 화면에서 확인</CopilotNavigationLink>}
        <Button type="button" variant="outline" className="copilot-quiet" disabled={state.busy} onClick={() => void store.retry(caseId, semanticProcessing, documentProcessing)}>실패한 질문 다시 조회</Button>
      </div>}
      <div ref={end} />
    </div>
    <form className="copilot-input" onSubmit={event => {
      event.preventDefault();
      if (!question.trim() || state.busy || !caseId) return;
      ask(question);
      setQuestion('');
    }}>
      <div className="copilot-input-row">
        <label className="sr-only" htmlFor="copilot-question">공고와 참가자격 질문</label>
        <textarea id="copilot-question" rows={1} maxLength={2000} value={question}
          onChange={event => setQuestion(event.target.value)}
          onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              event.currentTarget.form?.requestSubmit();
            }
          }}
          placeholder="공고나 우리 회사 참가자격에 대해 질문해 주세요"
          disabled={!caseId || state.busy} />
        <button type="submit" aria-label="질문 보내기" disabled={!caseId || state.busy || !question.trim()}><Send size={18} /></button>
      </div>
      <small>Enter 전송 · Shift+Enter 줄바꿈</small>
    </form>
  </>;
}

function SourceChip({ source, caseId, analysisRunId }: { source: CopilotSource; caseId: string; analysisRunId?: string }) {
  if (source.source_origin !== 'PRODUCT_EVIDENCE') return <span className="copilot-evidence-chip">[{source.ref}] {getSourceLocationLabel(source)}</span>;
  return <CopilotNavigationLink caseId={caseId} className="copilot-evidence-chip" href={`${href('/evidence', caseId)}&evidence=${encodeURIComponent(source.evidence.evidence_key)}${analysisRunId ? '&analysisRunId=' + encodeURIComponent(analysisRunId) : ''}`}>
    [{source.ref}] {getSourceLocationLabel(source)} · 원문
  </CopilotNavigationLink>;
}

function Answer({ response, caseId, onSelect }: { response: CopilotChatResponse; caseId: string; onSelect: (key: string) => void }) {
  const p = response.presentation;
  const { controller, action } = useActions(caseId);
  const { navigate } = useCopilotNavigation(caseId);
  const state = response.product_state;
  const changed = Boolean(state && 'changes' in state);
  const analysisRunId = state && 'analysis_run_id' in state.provenance ? state.provenance.analysis_run_id : undefined;
  const insufficient = response.sources.length === 0 && (
    response.intent === 'REQUIREMENT_EVIDENCE' || (response.intent === 'DOCUMENT_QA' && response.external_processing_used)
  );
  const kind = insufficient ? 'INSUFFICIENT_EVIDENCE' : changed ? 'CHANGED_NOTICE' : state && 'questions' in state ? 'NEEDS_CHECK' : 'ANSWER';
  const reasons = p?.reasons.filter(reason => reason.requirement_key) ?? [];
  const outside = p?.reasons.filter(reason => !reason.requirement_key) ?? [];
  const renderReason = (reason: NonNullable<typeof p>['reasons'][number], i: number) => <div key={`${reason.requirement_key ?? 'scope'}-${i}`} className="copilot-reason">
    {reason.requirement_key && <span className="copilot-reason-label">판정 요건 {i + 1}</span>}
    <p>{reason.text}</p>
    <div className="copilot-evidence-chips">{reason.evidence_refs.map(ref => {
      const source = response.sources.find(item => item.ref === ref);
      return source ? <SourceChip key={ref} source={source} caseId={caseId} analysisRunId={analysisRunId} /> : null;
    })}</div>
    {reason.requirement_key && <button type="button" className="copilot-detail-link" onClick={() => onSelect(reason.requirement_key!)}>이 요건 근거 보기</button>}
  </div>;
  return <article className={`copilot-answer${insufficient ? ' copilot-no-evidence' : ''}`} data-state={kind}>
    {response.envelope ? <EnvelopeAnswer envelope={response.envelope} /> : p ? <>
      <p className="copilot-conclusion">{p.conclusion}</p>
      {reasons.map(renderReason)}
      {outside.length > 0 && <div className="copilot-scope"><strong>{response.intent === 'DOCUMENT_QA' ? '사용한 공고문 근거' : '직접 확인할 공고 항목'}</strong>{outside.map(renderReason)}
        {response.intent !== 'DOCUMENT_QA' && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={`${href('/qualification', caseId)}#analysis-scope`}>참가자격 화면에서 함께 확인</CopilotNavigationLink>}
      </div>}
      {p.limitations.map((text, i) => <p className="copilot-limitation" key={i}>{text}</p>)}
      {p.next_action && <p>{p.next_action.label}</p>}
    </> : <p>{response.answer}</p>}
    {response.sources.length > 0 && <details><summary>원문 근거 {response.sources.length}건</summary>
      {response.sources.map(source => <div className="copilot-source" key={source.ref}>
        <SourceChip source={source} caseId={caseId} analysisRunId={analysisRunId} />
        <blockquote>{source.source_origin === 'PRODUCT_EVIDENCE' ? source.evidence.quote : source.quote}</blockquote>
      </div>)}
    </details>}
    {(insufficient || response.intent === 'DOCUMENT_QA') && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={href('/evidence', caseId)}>근거 원문 직접 확인</CopilotNavigationLink>}
    {changed && <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={href('/changes', caseId)}>변경사항 상세 보기 · 06</CopilotNavigationLink>}
    {state && 'profile_snapshot' in state && <details><summary>판정 당시 회사정보 · 현재 프로필과 다를 수 있음</summary><pre>{JSON.stringify(state.profile_snapshot, null, 2)}</pre></details>}
    {state && 'questions' in state && state.questions.filter(q => q.askable).map(q =>
      <Button type="button" variant="outline" className="copilot-quiet" key={q.requirement_key} disabled={isLocked(action)} onClick={async () => {
        await controller.beginAnswer(caseId, q.requirement_key,
          response.reply_context?.last_read_receipt?.kind === 'product' ? response.reply_context.last_read_receipt.provenance.judgment_run_id : undefined);
        navigate(href('/ask-back', caseId));
      }}>{q.question} · 답변 입력</Button>)}
    {response.actions.map((proposal, i) => <Button type="button" variant="outline" className="copilot-quiet" key={i} disabled={isLocked(action)} onClick={() => {
      controller.adopt(caseId, proposal);
      navigate(href(proposal.action_type === 'REVALIDATE' ? '/changes' : '/ask-back', caseId));
    }}>서버 제안 검토 · 아직 실행 안 함</Button>)}
  </article>;
}
