'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  FileSearch,
  FileText,
  FolderClock,
  LoaderCircle,
  RefreshCw,
  Upload,
} from 'lucide-react';

import { DocumentViewer } from '@/components/document-viewer';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import {
  ApiError,
  createPreflightCase,
  getNotice,
  getNoticeVersions,
  getPreflightCase,
  listNotices,
  listPreflightCases,
  uploadProposalDocument,
  type BidNoticeDetail,
  type BidNoticeSummary,
  type BidNoticeVersion,
  type NoticeDocument,
  type PreflightCase,
  type ProposalDocument,
} from '@/lib/api';

type BusyAction = 'load' | 'create' | 'upload' | null;

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    DRAFT: '제안서 대기',
    READY: '검토 준비 완료',
    PROCESSING: '처리 중',
    COMPLETED: '완료',
    FAILED: '실패',
    EXTRACTED: '텍스트 추출 완료',
    EMPTY: '텍스트 없음',
    UNSUPPORTED: '추출 미지원',
  };
  return labels[status] ?? status;
}

function formatBytes(bytes: number | null | undefined) {
  if (!bytes) return '-';
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024).toLocaleString()} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function documentLabel(document: NoticeDocument | ProposalDocument) {
  return `${document.name} · ${formatBytes(document.file_size_bytes)}`;
}

export default function Home() {
  const [notices, setNotices] = useState<BidNoticeSummary[]>([]);
  const [cases, setCases] = useState<PreflightCase[]>([]);
  const [notice, setNotice] = useState<BidNoticeDetail | null>(null);
  const [versions, setVersions] = useState<BidNoticeVersion[]>([]);
  const [activeCase, setActiveCase] = useState<PreflightCase | null>(null);
  const [noticeDocumentId, setNoticeDocumentId] = useState('');
  const [proposalDocumentId, setProposalDocumentId] = useState('');
  const [query, setQuery] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<BusyAction>('load');
  const uploadInput = useRef<HTMLInputElement>(null);

  const selectedVersion = useMemo(() => {
    if (!notice) return null;
    const versionNumber = activeCase?.current_version_number ?? notice.current_version;
    return versions.find((version) => version.version_number === versionNumber) ?? notice.latest;
  }, [activeCase, notice, versions]);

  const noticeDocuments = selectedVersion?.documents ?? [];
  const noticeDocument =
    noticeDocuments.find((document) => document.id === noticeDocumentId) ??
    noticeDocuments.find((document) => document.viewer_type === 'RHWP') ??
    noticeDocuments[0] ??
    null;
  const proposalDocuments = activeCase?.documents ?? [];
  const proposalDocument =
    proposalDocuments.find((document) => document.id === proposalDocumentId) ??
    proposalDocuments[0] ??
    null;

  async function loadNotice(noticeId: string, currentCase: PreflightCase | null) {
    const [detail, fetchedVersions] = await Promise.all([
      getNotice(noticeId),
      getNoticeVersions(noticeId),
    ]);
    setNotice(detail);
    setVersions(fetchedVersions);
    setNoticeDocumentId('');
    setActiveCase(currentCase);
    setProposalDocumentId(currentCase?.documents[0]?.id ?? '');
  }

  async function selectCase(caseId: string) {
    setError('');
    setBusy('load');
    try {
      const selected = await getPreflightCase(caseId);
      await loadNotice(selected.notice_id, selected);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건을 불러오지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function initialize() {
    setError('');
    setBusy('load');
    try {
      const [noticeResult, caseResult] = await Promise.all([
        listNotices(),
        listPreflightCases(),
      ]);
      setNotices(noticeResult.items);
      setCases(caseResult.items);
      if (caseResult.items[0]) {
        const selected = await getPreflightCase(caseResult.items[0].id);
        await loadNotice(selected.notice_id, selected);
      } else if (noticeResult.items[0]) {
        await loadNotice(noticeResult.items[0].id, null);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '백엔드 API에 연결하지 못했습니다.');
    } finally {
      setBusy(null);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => void initialize(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function searchNotices() {
    setBusy('load');
    setError('');
    try {
      const result = await listNotices(query);
      setNotices(result.items);
      if (result.items[0]) await loadNotice(result.items[0].id, null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '공고 검색에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function createCase() {
    if (!notice) return;
    setBusy('create');
    setError('');
    setMessage('');
    try {
      const olderVersion = versions.find(
        (version) => version.version_number < notice.current_version,
      );
      const created = await createPreflightCase({
        notice_id: notice.id,
        baseline_version_number: olderVersion?.version_number,
        current_version_number: notice.current_version,
        title: `${notice.bid_notice_no} 제안서 검토`,
      });
      const refreshed = await listPreflightCases();
      setCases(refreshed.items);
      await loadNotice(notice.id, created);
      setMessage('검토 건을 만들었습니다. 이제 제안서를 업로드하세요.');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건 생성에 실패했습니다.');
    } finally {
      setBusy(null);
    }
  }

  async function uploadFile(file: File | undefined) {
    if (!activeCase || !file) return;
    setBusy('upload');
    setError('');
    setMessage('');
    try {
      const uploaded = await uploadProposalDocument(activeCase.id, file);
      const refreshedCase = await getPreflightCase(activeCase.id);
      const refreshedCases = await listPreflightCases();
      setActiveCase(refreshedCase);
      setCases(refreshedCases.items);
      setProposalDocumentId(uploaded.id);
      setMessage(`${uploaded.name} 저장과 텍스트 추출을 완료했습니다.`);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : cause instanceof Error
            ? cause.message
            : '제안서 업로드에 실패했습니다.',
      );
    } finally {
      if (uploadInput.current) uploadInput.current.value = '';
      setBusy(null);
    }
  }

  const ready = activeCase?.status === 'READY';

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-40 flex h-14 items-center justify-between border-b bg-background/95 px-4 backdrop-blur md:px-6">
        <div className="flex items-center gap-3">
          <div className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground">
            <FileSearch className="size-4" />
          </div>
          <div>
            <h1 className="text-base font-semibold leading-none">입찰 변경 사전검토</h1>
            <p className="mt-1 text-xs text-muted-foreground">공고 원문과 제안서를 한 화면에서 확인합니다</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="hidden items-center gap-1.5 text-xs text-muted-foreground sm:flex">
            <span className={`size-2 rounded-full ${error ? 'bg-destructive' : 'bg-emerald-500'}`} />
            {error ? 'API 확인 필요' : 'API 연결됨'}
          </span>
          <Button variant="outline" size="sm" onClick={() => void initialize()} disabled={busy !== null}>
            <RefreshCw className={busy === 'load' ? 'animate-spin' : ''} /> 새로고침
          </Button>
        </div>
      </header>

      <div className="grid min-h-[calc(100vh-3.5rem)] grid-cols-1 xl:grid-cols-[300px_minmax(0,1fr)]">
        <aside className="border-b bg-sidebar p-4 xl:border-r xl:border-b-0">
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold">검토 건</h2>
              <Badge variant="secondary">{cases.length}</Badge>
            </div>
            <div className="max-h-44 space-y-2 overflow-y-auto pr-1 xl:max-h-[28vh]">
              {cases.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => void selectCase(item.id)}
                  className={`w-full rounded-xl border p-3 text-left transition-colors ${
                    activeCase?.id === item.id
                      ? 'border-primary bg-primary/8'
                      : 'bg-card hover:bg-accent'
                  }`}
                >
                  <div className="mb-1 flex items-center justify-between gap-2">
                    <span className="truncate text-xs font-semibold">{item.bid_notice_no}</span>
                    <span className={`size-2 shrink-0 rounded-full ${item.status === 'READY' ? 'bg-emerald-500' : 'bg-amber-400'}`} />
                  </div>
                  <p className="line-clamp-2 text-sm leading-5">{item.title}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{statusLabel(item.status)}</p>
                </button>
              ))}
              {!cases.length && (
                <div className="rounded-xl border border-dashed p-4 text-center text-sm text-muted-foreground">
                  생성된 검토 건이 없습니다.
                </div>
              )}
            </div>
          </section>

          <section className="mt-6 border-t pt-5">
            <h2 className="mb-3 text-sm font-semibold">새 검토 시작</h2>
            <form
              className="flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void searchNotices();
              }}
            >
              <Input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="공고번호 또는 공고명"
                aria-label="공고 검색"
              />
              <Button type="submit" variant="outline" disabled={busy !== null}>검색</Button>
            </form>
            <NativeSelect
              className="mt-2 w-full"
              aria-label="검토할 공고"
              value={notice?.id ?? ''}
              onChange={(event) => {
                const selected = notices.find((item) => item.id === event.target.value);
                if (selected) void loadNotice(selected.id, null);
              }}
            >
              {!notices.length && <NativeSelectOption value="">공고 없음</NativeSelectOption>}
              {notices.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.bid_notice_no} · {item.title}
                </NativeSelectOption>
              ))}
            </NativeSelect>
            <Button className="mt-2 w-full" onClick={() => void createCase()} disabled={!notice || busy !== null}>
              {busy === 'create' ? <LoaderCircle className="animate-spin" /> : <FolderClock />}
              검토 건 만들기
            </Button>
          </section>

          <section className="mt-6 border-t pt-5">
            <h2 className="text-sm font-semibold">제안서 파일</h2>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">HWP, HWPX, PDF, DOCX, TXT · 최대 100MB</p>
            <Input
              ref={uploadInput}
              className="mt-3 h-10 file:mr-2"
              type="file"
              aria-label="제안서 업로드"
              accept=".hwp,.hwpx,.pdf,.docx,.txt"
              disabled={!activeCase || busy !== null}
              onChange={(event) => void uploadFile(event.target.files?.[0])}
            />
            <div className="mt-3 space-y-2">
              {proposalDocuments.map((document) => (
                <button
                  type="button"
                  key={document.id}
                  onClick={() => setProposalDocumentId(document.id)}
                  className={`flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left text-xs ${
                    proposalDocument?.id === document.id ? 'border-primary bg-primary/8' : 'bg-card'
                  }`}
                >
                  <FileText className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1 truncate">{document.name}</span>
                  {document.extraction_status === 'EXTRACTED' && <CheckCircle2 className="size-4 shrink-0 text-emerald-600" />}
                </button>
              ))}
            </div>
          </section>
        </aside>

        <section className="min-w-0 p-3 md:p-4">
          <div className="mb-3 flex min-h-12 flex-col justify-between gap-2 rounded-xl border bg-card px-4 py-3 sm:flex-row sm:items-center">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <strong className="truncate text-sm">{activeCase?.title ?? notice?.title ?? '공고를 선택하세요'}</strong>
                {activeCase && <Badge variant={ready ? 'default' : 'secondary'}>{statusLabel(activeCase.status)}</Badge>}
              </div>
              {notice && (
                <p className="mt-1 truncate text-xs text-muted-foreground">
                  {notice.bid_notice_no} · {notice.announcing_institution_name ?? '공고기관 미상'}
                </p>
              )}
            </div>
            {activeCase && (
              <div className="flex shrink-0 gap-2 text-xs text-muted-foreground">
                <span>기준 v{activeCase.baseline_version_number ?? '-'}</span>
                <span>현재 v{activeCase.current_version_number}</span>
              </div>
            )}
          </div>

          {(error || message) && (
            <div className={`mb-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${error ? 'border-destructive/30 bg-destructive/5 text-destructive' : 'border-emerald-200 bg-emerald-50 text-emerald-800'}`}>
              {error ? <AlertCircle className="size-4" /> : <CheckCircle2 className="size-4" />}
              {error || message}
            </div>
          )}

          <div className="grid min-h-[calc(100vh-9.75rem)] grid-cols-1 gap-3 lg:grid-cols-3">
            <article className="document-panel">
              <div className="document-panel-header">
                <div>
                  <span className="panel-kicker">01 · 공고문</span>
                  <h2>현재 공고 원문</h2>
                </div>
                {noticeDocuments.length > 1 && (
                  <NativeSelect
                    size="sm"
                    className="max-w-48"
                    aria-label="공고 첨부파일"
                    value={noticeDocument?.id ?? ''}
                    onChange={(event) => setNoticeDocumentId(event.target.value)}
                  >
                    {noticeDocuments.map((document) => (
                      <NativeSelectOption key={document.id} value={document.id}>{document.name}</NativeSelectOption>
                    ))}
                  </NativeSelect>
                )}
              </div>
              <DocumentViewer document={noticeDocument} emptyMessage="저장된 공고 원문이 없습니다." />
              {noticeDocument && <p className="document-meta">{documentLabel(noticeDocument)}</p>}
            </article>

            <article className="document-panel">
              <div className="document-panel-header">
                <div>
                  <span className="panel-kicker">02 · 제안서</span>
                  <h2>제출 문서 원문</h2>
                </div>
                {busy === 'upload' && <LoaderCircle className="size-4 animate-spin text-primary" />}
              </div>
              <DocumentViewer
                document={proposalDocument}
                emptyMessage={activeCase ? '왼쪽에서 제안서를 업로드하세요.' : '먼저 검토 건을 만드세요.'}
              />
              {proposalDocument && <p className="document-meta">{documentLabel(proposalDocument)}</p>}
            </article>

            <article className="document-panel">
              <div className="document-panel-header">
                <div>
                  <span className="panel-kicker">03 · 검토 결과</span>
                  <h2>누락·합격조건</h2>
                </div>
                <Badge variant={ready ? 'default' : 'outline'}>{ready ? '준비됨' : '대기'}</Badge>
              </div>
              <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4">
                {activeCase ? (
                  <>
                    <div className={`rounded-xl border p-4 ${ready ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'}`}>
                      <div className="flex items-start gap-3">
                        {ready ? <CheckCircle2 className="mt-0.5 size-5 text-emerald-700" /> : <Upload className="mt-0.5 size-5 text-amber-700" />}
                        <div>
                          <strong className="text-sm">{ready ? '검토 입력 준비 완료' : '제안서 업로드 필요'}</strong>
                          <p className="mt-1 text-sm leading-6 text-muted-foreground">
                            {ready
                              ? '공고문과 제안서 원문 및 추출 텍스트가 준비됐습니다.'
                              : '제안서를 저장하고 텍스트 추출을 끝내면 검토 가능한 상태가 됩니다.'}
                          </p>
                        </div>
                      </div>
                    </div>
                    <dl className="mt-5 space-y-3 text-sm">
                      <div className="flex justify-between border-b pb-3"><dt className="text-muted-foreground">현재 공고</dt><dd className="font-medium">v{activeCase.current_version_number}</dd></div>
                      <div className="flex justify-between border-b pb-3"><dt className="text-muted-foreground">비교 기준</dt><dd className="font-medium">{activeCase.baseline_version_number ? `v${activeCase.baseline_version_number}` : '없음'}</dd></div>
                      <div className="flex justify-between border-b pb-3"><dt className="text-muted-foreground">제안서 파일</dt><dd className="font-medium">{proposalDocuments.length}개</dd></div>
                      <div className="flex justify-between border-b pb-3"><dt className="text-muted-foreground">텍스트 추출</dt><dd className="font-medium">{proposalDocument ? statusLabel(proposalDocument.extraction_status) : '-'}</dd></div>
                      <div className="flex justify-between border-b pb-3"><dt className="text-muted-foreground">추출 글자 수</dt><dd className="font-medium">{proposalDocument?.extracted_char_count?.toLocaleString() ?? '-'}자</dd></div>
                    </dl>
                    <div className="mt-auto rounded-lg bg-muted p-3 text-xs leading-5 text-muted-foreground">
                      현재 단계에서는 문서 저장·원문 표시·텍스트 추출 상태만 제공합니다. 누락 및 합격조건 결과는 분석 결과 연동 후 이 영역에 표시됩니다.
                    </div>
                  </>
                ) : (
                  <div className="grid flex-1 place-items-center text-center text-sm text-muted-foreground">
                    <div><FileSearch className="mx-auto mb-3 size-8 opacity-40" />검토 건을 만들면 문서 준비 상태가 표시됩니다.</div>
                  </div>
                )}
              </div>
            </article>
          </div>
        </section>
      </div>
    </main>
  );
}
