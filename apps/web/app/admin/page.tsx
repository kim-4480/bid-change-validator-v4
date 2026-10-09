'use client';

import { useEffect, useState, type SyntheticEvent } from 'react';
import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { getCurrentUser, type AuthUser } from '@/lib/auth';
import { listHistoryJobs, retryHistoryJob, type HistoryJob } from '@/lib/admin-jobs-api';
import { approveRelevanceReview, listRelevanceEvents, listRelevanceLabels, reopenRelevanceReview, submitRelevanceReview, type RelevanceEvent, type RelevanceLabel } from '@/lib/admin-relevance-api';
import { approveProcessingAnalysis, listProcessingAttempts, listProcessingJobs, retryProcessingJob, type ProcessingAttempt, type ProcessingJob } from '@/lib/admin-processing-api';

type AdminState = { loading: boolean; user: AuthUser | null; error: string };
const EMPTY: AdminState = { loading: true, user: null, error: '' };

export default function AdminPage() {
  const [state, setState] = useState<AdminState>(EMPTY);
  const [attempt, setAttempt] = useState(0);
  const [jobs, setJobs] = useState<HistoryJob[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [jobsBusy, setJobsBusy] = useState(false);
  const [labels, setLabels] = useState<RelevanceLabel[]>([]);
  const [labelError, setLabelError] = useState<string | null>(null);
  const [labelBusy, setLabelBusy] = useState(false);
  const [companyId, setCompanyId] = useState('');
  const [noticeVersionId, setNoticeVersionId] = useState('');
  const [grade, setGrade] = useState(2);
  const [origin, setOrigin] = useState<'REAL' | 'SYNTHETIC' | 'UNKNOWN'>('UNKNOWN');
  const [rationale, setRationale] = useState('');
  const [events, setEvents] = useState<RelevanceEvent[]>([]);
  const [selectedLabelId, setSelectedLabelId] = useState<string | null>(null);
  const [processingJobs, setProcessingJobs] = useState<ProcessingJob[]>([]);
  const [processingError, setProcessingError] = useState<string | null>(null);
  const [processingBusy, setProcessingBusy] = useState(false);
  const [analysisVersionId, setAnalysisVersionId] = useState('');
  const [attemptsByJob, setAttemptsByJob] = useState<Record<string, ProcessingAttempt[]>>({});

  useEffect(() => {
    let active = true;
    void getCurrentUser()
      .then((user) => { if (active) setState({ loading: false, user, error: '' }); })
      .catch((error: unknown) => {
        if (active) setState({ loading: false, user: null, error: error instanceof Error ? error.message : '권한을 확인하지 못했습니다.' });
      });
    return () => { active = false; };
  }, [attempt]);

  const canView = state.user?.role === 'SYSTEM_ADMIN' || state.user?.role === 'ADMIN';

  useEffect(() => {
    if (!canView) return;
    let active = true;
    void listRelevanceLabels()
      .then((items) => { if (active) setLabels(items); })
      .catch((error: unknown) => { if (active) setLabelError(error instanceof Error ? error.message : '라벨 조회에 실패했습니다.'); });
    return () => { active = false; };
  }, [canView, state.user?.role, state.user?.company_id]);

  async function refreshLabels() {
    setLabelBusy(true);
    setLabelError(null);
    try { setLabels(await listRelevanceLabels()); }
    catch (error) { setLabelError(error instanceof Error ? error.message : '라벨 조회에 실패했습니다.'); }
    finally { setLabelBusy(false); }
  }

  async function submitLabel(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setLabelBusy(true);
    setLabelError(null);
    try {
      await submitRelevanceReview({ company_id: state.user?.role === 'ADMIN' ? state.user.company_id ?? '' : companyId, notice_version_id: noticeVersionId, grade, subject_origin: origin, rationale });
      setRationale('');
      setLabels(await listRelevanceLabels());
    } catch (error) { setLabelError(error instanceof Error ? error.message : '검수 저장에 실패했습니다.'); }
    finally { setLabelBusy(false); }
  }

  async function approveLabel(label: RelevanceLabel) {
    if (!window.confirm('실제 기업임을 독립적으로 확인했고 이 라벨을 학습 후보로 승인하시겠습니까?')) return;
    setLabelBusy(true);
    setLabelError(null);
    try { await approveRelevanceReview(label.id); setLabels(await listRelevanceLabels()); }
    catch (error) { setLabelError(error instanceof Error ? error.message : '승인에 실패했습니다.'); }
    finally { setLabelBusy(false); }
  }

  async function reopenLabel(label: RelevanceLabel) {
    if (!window.confirm('승인된 라벨을 학습 내보내기에서 제외하고 새 검수를 요청하시겠습니까?')) return;
    setLabelBusy(true);
    setLabelError(null);
    try { await reopenRelevanceReview(label.id); setLabels(await listRelevanceLabels()); }
    catch (error) { setLabelError(error instanceof Error ? error.message : '재검수 요청에 실패했습니다.'); }
    finally { setLabelBusy(false); }
  }

  async function showEvents(label: RelevanceLabel) {
    setLabelError(null);
    try { setEvents(await listRelevanceEvents(label.id)); setSelectedLabelId(label.id); }
    catch (error) { setLabelError(error instanceof Error ? error.message : '감사 이력 조회에 실패했습니다.'); }
  }

  async function refreshJobs() {
    setJobsBusy(true);
    setJobsError(null);
    try {
      setJobs(await listHistoryJobs());
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : '작업 조회에 실패했습니다.');
    } finally {
      setJobsBusy(false);
    }
  }

  useEffect(() => {
    if (state.user?.role !== 'SYSTEM_ADMIN') return;
    let active = true;
    void listHistoryJobs()
      .then((items) => { if (active) setJobs(items); })
      .catch((error: unknown) => {
        if (active) setJobsError(error instanceof Error ? error.message : '작업 조회에 실패했습니다.');
      });
    return () => { active = false; };
  }, [state.user?.role]);

  useEffect(() => {
    if (state.user?.role !== 'SYSTEM_ADMIN') return;
    let active = true;
    void listProcessingJobs()
      .then((items) => { if (active) setProcessingJobs(items); })
      .catch((error: unknown) => { if (active) setProcessingError(error instanceof Error ? error.message : '처리 작업 조회에 실패했습니다.'); });
    return () => { active = false; };
  }, [state.user?.role]);

  async function refreshProcessing() {
    setProcessingBusy(true);
    setProcessingError(null);
    try { setProcessingJobs(await listProcessingJobs()); }
    catch (error) { setProcessingError(error instanceof Error ? error.message : '처리 작업 조회에 실패했습니다.'); }
    finally { setProcessingBusy(false); }
  }

  async function approveAnalysis(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!window.confirm('이 공고 차수와 현재 추출 문서에 한해서 외부 LLM 분석 작업을 승인하시겠습니까? 비용이 발생할 수 있습니다.')) return;
    setProcessingBusy(true);
    setProcessingError(null);
    try {
      await approveProcessingAnalysis(analysisVersionId);
      setAnalysisVersionId('');
      setProcessingJobs(await listProcessingJobs());
    } catch (error) { setProcessingError(error instanceof Error ? error.message : '분석 승인에 실패했습니다.'); }
    finally { setProcessingBusy(false); }
  }

  async function retryProcessing(job: ProcessingJob) {
    if (!window.confirm(`${job.stage} 실패 작업을 재대기할까요? 외부 처리 워커가 켜져 있으면 비용이 발생할 수 있습니다.`)) return;
    setProcessingBusy(true);
    setProcessingError(null);
    try { await retryProcessingJob(job.id); setProcessingJobs(await listProcessingJobs()); }
    catch (error) { setProcessingError(error instanceof Error ? error.message : '처리 작업 재대기에 실패했습니다.'); }
    finally { setProcessingBusy(false); }
  }

  async function showProcessingAttempts(job: ProcessingJob) {
    setProcessingError(null);
    try { setAttemptsByJob((current) => ({ ...current, [job.id]: [] })); const attempts = await listProcessingAttempts(job.id); setAttemptsByJob((current) => ({ ...current, [job.id]: attempts })); }
    catch (error) { setProcessingError(error instanceof Error ? error.message : '실행 이력 조회에 실패했습니다.'); }
  }

  async function retryJob(job: HistoryJob) {
    if (!window.confirm(`공고 ${job.notice_id}의 실패한 이력 수집 작업을 재대기시킬까요? 즉시 실행되지는 않습니다.`)) return;
    setJobsBusy(true);
    setJobsError(null);
    try {
      await retryHistoryJob(job.id);
      setJobs(await listHistoryJobs());
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : '재대기에 실패했습니다.');
    } finally {
      setJobsBusy(false);
    }
  }

  return (
    <main className="app-shell-container py-8 pb-16">
      <h1 className="text-2xl font-bold">운영 작업 관리</h1>
      {state.loading ? (
        <output aria-live="polite" className="mt-6 block rounded-xl border p-5">관리자 권한을 확인하고 있습니다.</output>
      ) : state.error ? (
        <div role="alert" className="mt-6 rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
          {state.error} <Button size="sm" variant="outline" onClick={() => setAttempt((value) => value + 1)}>다시 시도</Button>
        </div>
      ) : !canView ? (
        <div role="alert" className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">
          관리자만 접근할 수 있습니다. <NavigationLink href="/notices" className="underline">공고 목록으로 이동</NavigationLink>
        </div>
      ) : (
        <>
          <p className="mt-3 text-sm text-slate-600">현재 사용자 역할: {state.user?.role}</p>
          {state.user?.role === 'SYSTEM_ADMIN' && (
            <section className="mt-6 rounded-xl border bg-white p-5" aria-labelledby="history-jobs-heading">
              <div className="flex items-center justify-between gap-3">
                <h2 id="history-jobs-heading" className="font-bold">공고 이력 수집 작업</h2>
                <Button type="button" size="sm" variant="outline" disabled={jobsBusy} onClick={() => void refreshJobs()}>새로고침</Button>
              </div>
              <p className="mt-2 text-sm text-slate-600">최근 50건을 조회합니다. 재시도는 실패 작업을 대기 상태로만 바꿉니다.</p>
              {jobsError && <p role="alert" className="mt-3 text-sm text-red-700">{jobsError}</p>}
              {!jobsError && jobs.length === 0 && <p className="mt-3 text-sm text-slate-600">표시할 작업이 없습니다.</p>}
              <ul className="mt-3 space-y-3">
                {jobs.map((job) => (
                  <li key={job.id} className="rounded-lg border p-3 text-sm">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="break-all font-semibold">공고 {job.notice_id}</span>
                      <span>{job.status} · 시도 {job.attempts}회</span>
                    </div>
                    {job.last_error && <p className="mt-2 break-words text-red-700">마지막 오류: {job.last_error}</p>}
                    {job.status === 'FAILED' && (
                      <Button type="button" className="mt-3" size="sm" variant="outline" disabled={jobsBusy} onClick={() => void retryJob(job)}>선택 재대기</Button>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {state.user?.role === 'SYSTEM_ADMIN' && (
            <section className="mt-6 rounded-xl border bg-white p-5" aria-labelledby="processing-jobs-heading">
              <div className="flex items-center justify-between gap-3">
                <h2 id="processing-jobs-heading" className="font-bold">공고 차수별 처리 작업</h2>
                <Button type="button" size="sm" variant="outline" disabled={processingBusy} onClick={() => void refreshProcessing()}>새로고침</Button>
              </div>
              <p className="mt-2 text-sm text-slate-600">추출·추천 특징은 내부 작업입니다. 임베딩·LLM 워커는 기본 비활성이며, LLM 분석은 차수별 명시 승인도 필요합니다.</p>
              <form className="mt-3 flex flex-wrap gap-2" onSubmit={(event) => void approveAnalysis(event)}>
                <input aria-label="분석 승인할 공고 차수 ID" className="min-w-64 flex-1 rounded-md border p-2 text-sm" required value={analysisVersionId} onChange={(event) => setAnalysisVersionId(event.target.value)} placeholder="공고 차수 ID" />
                <Button type="submit" size="sm" disabled={processingBusy}>LLM 분석 승인</Button>
              </form>
              {processingError && <p role="alert" className="mt-3 text-sm text-red-700">{processingError}</p>}
              {processingJobs.length === 0 && <p className="mt-3 text-sm text-slate-600">표시할 처리 작업이 없습니다.</p>}
              <ul className="mt-3 space-y-3">
                {processingJobs.map((job) => (
                  <li key={job.id} className="rounded-lg border p-3 text-sm">
                    <p className="break-all font-semibold">{job.stage} · 차수 {job.notice_version_id}</p>
                    <p className="mt-1">{job.status} · 시도 {job.attempts}/{job.retry_budget} · 우선순위 {job.priority}</p>
                    {job.last_error && <p className="mt-1 break-words text-red-700">오류: {job.last_error}</p>}
                    <div className="mt-2 flex gap-2">
                      <Button type="button" size="sm" variant="outline" onClick={() => void showProcessingAttempts(job)}>실행 이력</Button>
                      {job.status === 'FAILED' && job.attempts >= job.retry_budget && <Button type="button" size="sm" variant="outline" disabled={processingBusy} onClick={() => void retryProcessing(job)}>선택 재대기</Button>}
                    </div>
                    {attemptsByJob[job.id] && <ul className="mt-2 border-t pt-2 text-xs text-slate-600">
                      {attemptsByJob[job.id].map((attempt) => <li key={attempt.attempt_number}>{attempt.attempt_number}회 · {attempt.outcome} · {new Date(attempt.started_at).toLocaleString('ko-KR')} {attempt.error ?? ''}</li>)}
                    </ul>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section className="mt-6 rounded-xl border bg-white p-5" aria-labelledby="relevance-labels-heading">
            <div className="flex items-center justify-between gap-3">
              <h2 id="relevance-labels-heading" className="font-bold">기업–공고 연관성 사람 검수</h2>
              <Button type="button" size="sm" variant="outline" disabled={labelBusy} onClick={() => void refreshLabels()}>새로고침</Button>
            </div>
            <p className="mt-2 text-sm text-slate-600">0~3점은 사업 연관성 라벨이며, 참가자격 충족이나 낙찰 확률이 아닙니다. 실제 기업 여부·근거를 검수한 뒤 다른 시스템 관리자가 승인해야 학습 후보로 내보낼 수 있습니다.</p>
            <form className="mt-4 grid gap-3 sm:grid-cols-2" onSubmit={(event) => void submitLabel(event)}>
              <label className="text-sm">기업 ID
                <input className="mt-1 w-full rounded-md border p-2" required value={state.user?.role === 'ADMIN' ? state.user.company_id ?? '' : companyId} readOnly={state.user?.role === 'ADMIN'} onChange={(event) => setCompanyId(event.target.value)} />
              </label>
              <label className="text-sm">공고 차수 ID
                <input className="mt-1 w-full rounded-md border p-2" required value={noticeVersionId} onChange={(event) => setNoticeVersionId(event.target.value)} />
              </label>
              <label className="text-sm">사업 연관성 점수
                <select className="mt-1 w-full rounded-md border p-2" value={grade} onChange={(event) => setGrade(Number(event.target.value))}>
                  <option value={0}>0 · 무관</option><option value={1}>1 · 약한 연관</option>
                  <option value={2}>2 · 관련 가능</option><option value={3}>3 · 강한 연관</option>
                </select>
              </label>
              <label className="text-sm">기업 출처
                <select className="mt-1 w-full rounded-md border p-2" value={origin} onChange={(event) => setOrigin(event.target.value as typeof origin)}>
                  <option value="UNKNOWN">미확인</option><option value="SYNTHETIC">합성</option><option value="REAL">실제 기업 · 검수자 확인</option>
                </select>
              </label>
              <label className="text-sm sm:col-span-2">검수 근거 (10자 이상)
                <textarea className="mt-1 min-h-24 w-full rounded-md border p-2" required minLength={10} value={rationale} onChange={(event) => setRationale(event.target.value)} />
              </label>
              <Button type="submit" disabled={labelBusy} className="sm:col-span-2">검수 초안 저장</Button>
            </form>
            {labelError && <p role="alert" className="mt-3 text-sm text-red-700">{labelError}</p>}
            <h3 className="mt-6 font-semibold">최근 검수 {labels.length}건</h3>
            {labels.length === 0 && <p className="mt-2 text-sm text-slate-600">아직 입력된 라벨이 없습니다. 승인된 실제 학습 라벨도 없습니다.</p>}
            <ul className="mt-3 space-y-3">
              {labels.map((label) => (
                <li key={label.id} className="rounded-lg border p-3 text-sm">
                  <p className="break-all font-medium">기업 {label.company_id} · 공고 차수 {label.notice_version_id}</p>
                  <p className="mt-1">{label.grade}점 · {label.subject_origin} · {label.status} · 검수 {new Date(label.reviewed_at).toLocaleString('ko-KR')}</p>
                  <p className="mt-1 break-words">{label.rationale}</p>
                  <div className="mt-2 flex gap-2">
                    <Button type="button" size="sm" variant="outline" onClick={() => void showEvents(label)}>감사 이력</Button>
                    {state.user?.role === 'SYSTEM_ADMIN' && label.status === 'DRAFT' && label.subject_origin === 'REAL' && label.reviewer_id !== state.user.id && (
                      <Button type="button" size="sm" disabled={labelBusy} onClick={() => void approveLabel(label)}>독립 승인</Button>
                    )}
                    {state.user?.role === 'SYSTEM_ADMIN' && label.status === 'APPROVED' && (
                      <Button type="button" size="sm" variant="outline" disabled={labelBusy} onClick={() => void reopenLabel(label)}>재검수 요청</Button>
                    )}
                  </div>
                  {selectedLabelId === label.id && <ul className="mt-2 border-t pt-2 text-xs text-slate-600">
                    {events.map((entry) => <li key={entry.id}>{entry.action} · 담당 {entry.actor_id} · {new Date(entry.created_at).toLocaleString('ko-KR')}</li>)}
                  </ul>}
                </li>
              ))}
            </ul>
          </section>
          <output className="mt-6 block rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
            수집 후 추출·특징 갱신 작업은 차수별 영속 큐에 기록됩니다. 임베딩·LLM 워커는 기본 비활성이며, 운영 배포·실행은 별도 승인이 필요합니다.
          </output>
        </>
      )}
    </main>
  );
}
