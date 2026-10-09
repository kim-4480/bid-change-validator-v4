'use client';

import { useEffect, useState } from 'react';
import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { getCurrentUser, type AuthUser } from '@/lib/auth';
import { listHistoryJobs, retryHistoryJob, type HistoryJob } from '@/lib/admin-jobs-api';

type AdminState = { loading: boolean; user: AuthUser | null; error: string };
const EMPTY: AdminState = { loading: true, user: null, error: '' };
const OPERATIONS = [
  { title: '문서 추출·분석 작업', detail: '범용 작업 큐와 관리자 API는 아직 연결되지 않았습니다.' },
  { title: '라벨 검수', detail: '사람이 승인한 라벨만 학습·평가에 반영' },
];

export default function AdminPage() {
  const [state, setState] = useState<AdminState>(EMPTY);
  const [attempt, setAttempt] = useState(0);
  const [jobs, setJobs] = useState<HistoryJob[]>([]);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [jobsBusy, setJobsBusy] = useState(false);

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
          <output className="mt-6 block rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
            공고 이력 수집 작업 외의 범용 작업 큐와 라벨 검수·승인 API는 아직 통합되지 않았습니다.
            아래 항목은 작업 범위만 안내하며 실제 완료로 표시하지 않습니다.
          </output>
          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {OPERATIONS.map((operation) => (
              <section key={operation.title} className="rounded-xl border bg-white p-5">
                <h2 className="font-bold">{operation.title}</h2>
                <p className="mt-2 text-sm text-slate-600">{operation.detail}</p>
                <p className="mt-3 text-xs font-semibold text-amber-800">API 계약 대기 · 실행 불가</p>
              </section>
            ))}
          </div>
        </>
      )}
    </main>
  );
}
