'use client';

import { useEffect, useState } from 'react';
import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { getCurrentUser, type AuthUser } from '@/lib/auth';

type AdminState = { loading: boolean; user: AuthUser | null; error: string };
const EMPTY: AdminState = { loading: true, user: null, error: '' };
const OPERATIONS = [
  { title: '실패 작업 조회', detail: '실패 작업 목록 및 발생 원인 확인' },
  { title: '작업 상태 확인', detail: '수집·추출·분석 작업 상태 및 이력 확인' },
  { title: '선택 재처리', detail: '대상·버전·영향 범위를 확인한 뒤 개별 승인' },
  { title: '라벨 검수', detail: '사람이 승인한 라벨만 학습·평가에 반영' },
];

export default function AdminPage() {
  const [state, setState] = useState<AdminState>(EMPTY);
  const [attempt, setAttempt] = useState(0);

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
          <output className="mt-6 block rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm leading-6 text-amber-900">
            운영 작업 및 라벨 검수 API 계약이 아직 통합되지 않았습니다.
            조회·재처리·승인 API를 추측하여 호출하지 않으며, 실제 작업 완료로 표시하지 않습니다.
            아래 항목은 작업 범위만 안내합니다.
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
