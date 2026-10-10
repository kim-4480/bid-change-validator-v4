'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { DocumentViewer } from '@/components/document-viewer';
import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { getNotice, getNoticeVersions, type BidNoticeDetail, type BidNoticeVersion } from '@/lib/api';

type DetailState = { loading: boolean; error: string; notice: BidNoticeDetail | null; versions: BidNoticeVersion[] };
const EMPTY: DetailState = { loading: true, error: '', notice: null, versions: [] };

export default function NoticeDetailPage() {
  const params = useParams<{ noticeId: string }>();
  const noticeId = params.noticeId;
  const [state, setState] = useState<DetailState>(EMPTY);
  const [requestedVersion, setRequestedVersion] = useState<number | null>(null);
  const [selectedDocumentId, setSelectedDocumentId] = useState('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    Promise.all([getNotice(noticeId), getNoticeVersions(noticeId)])
      .then(([notice, versions]) => {
        if (active) setState({ loading: false, error: '', notice, versions });
      })
      .catch((error: unknown) => {
        if (active) setState({ loading: false, error: error instanceof Error ? error.message : '공고를 불러오지 못했습니다.', notice: null, versions: [] });
      });
    return () => { active = false; };
  }, [noticeId, attempt]);

  const selectedVersion = state.versions.find((version) => version.version_number === requestedVersion)
    ?? state.versions.find((version) => version.is_current)
    ?? state.notice?.latest ?? null;
  const documents = selectedVersion?.documents ?? [];
  const selectedDocument = documents.find((doc) => doc.id === selectedDocumentId) ?? documents[0] ?? null;

  return (
    <main className="app-shell-container min-w-0 py-8 pb-16">
      <NavigationLink href="/notices" className="text-sm font-semibold text-blue-700 underline">공고 목록으로</NavigationLink>
      {state.loading ? (
        <output aria-live="polite" className="mt-6 block rounded-xl border p-5">공고 상세 및 첨부 원문을 불러오는 중입니다.</output>
      ) : state.error || !state.notice ? (
        <div role="alert" className="mt-6 rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
          {state.error || '공고가 없습니다.'}
          <Button variant="outline" size="sm" className="ml-3" onClick={() => setAttempt((value) => value + 1)}>다시 시도</Button>
        </div>
      ) : (
        <>
          <section className="mt-6 rounded-2xl border bg-white p-5 sm:p-7">
            <p className="text-xs font-semibold text-slate-600">{state.notice.bid_notice_no}</p>
            <h1 className="mt-2 break-words text-2xl font-bold text-slate-900">{state.notice.title}</h1>
            <dl className="mt-5 grid gap-4 text-sm sm:grid-cols-2">
              <div><dt className="text-slate-500">공고기관</dt><dd className="font-medium">{state.notice.announcing_institution_name ?? '미확인'}</dd></div>
              <div><dt className="text-slate-500">수요기관</dt><dd className="font-medium">{state.notice.demanding_institution_name ?? '미확인'}</dd></div>
              <div><dt className="text-slate-500">현행 버전</dt><dd className="font-medium">{state.notice.current_version}</dd></div>
              <div><dt className="text-slate-500">입찰 마감</dt><dd className="font-medium">{state.notice.latest.bid_closed_at ?? '미확인'}</dd></div>
            </dl>
            <div className="mt-5 flex flex-wrap gap-4">
              <NavigationLink href="/qualification" className="font-semibold text-blue-700 underline">참가자격 검토 열기</NavigationLink>
              <NavigationLink href="/changes" className="font-semibold text-blue-700 underline">변경공고 확인</NavigationLink>
            </div>
          </section>
          <section className="mt-6 rounded-2xl border bg-white p-5 sm:p-7" aria-labelledby="source-title">
            <h2 id="source-title" className="text-xl font-bold">버전별 첨부 원문</h2>
            <div className="mt-4 flex flex-wrap gap-4">
              <label className="flex flex-col gap-1 text-sm font-medium" htmlFor="notice-version">공고 버전
                <select id="notice-version" className="rounded-lg border px-3 py-2"
                  value={selectedVersion?.version_number ?? ''}
                  onChange={(event) => { setRequestedVersion(Number(event.target.value)); setSelectedDocumentId(''); }}>
                  {state.versions.map((version) => (
                    <option key={version.id} value={version.version_number}>
                      {version.version_number}{version.is_current ? ' (현재)' : ' (이전)'}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-medium" htmlFor="notice-attachment">첨부 문서
                <select id="notice-attachment" className="w-full rounded-lg border px-3 py-2"
                  value={selectedDocument?.id ?? ''} disabled={!documents.length}
                  onChange={(event) => setSelectedDocumentId(event.target.value)}>
                  {documents.length ? documents.map((doc) => <option key={doc.id} value={doc.id}>{doc.name}</option>)
                    : <option value="">첨부 문서 없음</option>}
                </select>
              </label>
            </div>
            <p className="mt-3 text-xs text-slate-600">추출에 실패한 파일은 원문 미확보 상태로 취급하며, 자격 충족으로 간주하지 않습니다.</p>
            <div className="mt-4 flex min-h-[450px] min-w-0 flex-col overflow-hidden rounded-xl border bg-slate-50">
              <DocumentViewer document={selectedDocument} emptyMessage="해당 버전의 첨부 원문이 없습니다." />
            </div>
          </section>
        </>
      )}
    </main>
  );
}
