'use client';

import { useRouter } from 'next/navigation';
import { sharedQueryClient } from '@/lib/shared-query-cache';

import { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  FileCheck2,
  LayoutGrid,
  LoaderCircle,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
  type LucideIcon,
} from 'lucide-react';

import { CachedNoticeMatches } from '@/components/product/cached-notice-matches';
import { NOTICE_PAGE_SIZE, noticePageRange } from '@/lib/notice-pagination';
import { NavigationLink } from '@/components/navigation-link';
import { Button, buttonVariants } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { findPreflightCasesByNotice, getNoticeVersions, listNotices, type BidNoticeSummary } from '@/lib/api';
import { createPreflightCaseWithCompany, listCompanies, type CompanyProfile } from '@/lib/qualification-api';
import { productProfileCoverage } from '@/lib/product-profile';
import { ASK_BACK_REASON_COPY, BUSINESS_TYPE_LABEL, labelOf, OVERALL_STATUS_BADGE } from '@/lib/status-copy';
type OverallStatus = 'core_met' | 'core_unmet' | 'unreviewed' | 'needs_review';
type StatusFilter = 'all' | OverallStatus;
type QuickTile = { label: string; value: string | number; icon: LucideIcon; filter: StatusFilter };
const EMPTY_COUNTS: Record<OverallStatus, number> = {
  core_met: 0, core_unmet: 0, unreviewed: 0, needs_review: 0,
};

type NoticeView = {
  notices: BidNoticeSummary[];
  total: number;
  counts: Record<OverallStatus, number>;
  company: CompanyProfile | null;
  query: string;
  page: number;
  status: StatusFilter;
  businessType: string;
};
function previousNotices(): NoticeView | undefined {
  return sharedQueryClient().getQueryData<NoticeView>(['view', 'notices']);
}
export default function NoticesPage() {
  const router = useRouter();
  const [notices, setNotices] = useState<BidNoticeSummary[]>(() => previousNotices()?.notices ?? []);
  const [noticeTotal, setNoticeTotal] = useState(() => previousNotices()?.total ?? 0);
  const [statusCounts, setStatusCounts] = useState<Record<OverallStatus, number>>(() => previousNotices()?.counts ?? EMPTY_COUNTS);
  const [company, setCompany] = useState<CompanyProfile | null>(() => previousNotices()?.company ?? null);
  const [query, setQuery] = useState(() => previousNotices()?.query ?? '');
  const [activeQuery, setActiveQuery] = useState(() => previousNotices()?.query ?? '');
  const [pageIndex, setPageIndex] = useState(() => previousNotices()?.page ?? 0);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(() => previousNotices()?.status ?? 'all');
  const [businessTypeFilter, setBusinessTypeFilter] = useState(() => previousNotices()?.businessType ?? 'all');
  const [loading, setLoading] = useState(() => !previousNotices());
  const [creatingNoticeId, setCreatingNoticeId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [showRejected, setShowRejected] = useState(true);
  const searchGeneration = useRef(0);
  const companyCache = useRef<CompanyProfile | null>(previousNotices()?.company ?? null);

  async function initialize(
    searchQuery = activeQuery,
    nextPage = pageIndex,
    selectedBusinessType = businessTypeFilter,
    selectedStatus: StatusFilter = statusFilter,
  ) {
    const generation = ++searchGeneration.current;
    const normalizedQuery = searchQuery.trim();
    setActiveQuery(normalizedQuery);
    setPageIndex(nextPage);
    setStatusFilter(selectedStatus);
    setLoading(true);
    setError('');
    try {
      if (!companyCache.current) {
        const companies = await listCompanies();
        if (generation !== searchGeneration.current) return;
        companyCache.current = companies[0] ?? null;
      }
      const selectedCompany = companyCache.current;
      if (!selectedCompany && selectedStatus !== 'all') {
        throw new Error('판정 상태 필터를 사용하려면 회사 프로필이 필요합니다.');
      }
      const result = await listNotices(normalizedQuery, {
        limit: NOTICE_PAGE_SIZE,
        offset: nextPage * NOTICE_PAGE_SIZE,
        businessType: selectedBusinessType,
        companyId: selectedCompany?.id,
        qualificationStatus: selectedStatus,
      });
      if (generation !== searchGeneration.current) return;
      if (nextPage > 0 && nextPage * NOTICE_PAGE_SIZE >= result.total) {
        void initialize(
          normalizedQuery, Math.max(0, Math.ceil(result.total / NOTICE_PAGE_SIZE) - 1),
          selectedBusinessType, selectedStatus,
        );
        return;
      }
      setCompany(selectedCompany);
      setNotices(result.items);
      setNoticeTotal(result.total);
      setStatusCounts({ ...EMPTY_COUNTS, ...result.status_counts });
      sharedQueryClient().setQueryData<NoticeView>(['view', 'notices'], {
        notices: result.items, total: result.total, counts: { ...EMPTY_COUNTS, ...result.status_counts },
        company: selectedCompany, query: normalizedQuery, page: nextPage,
        status: selectedStatus, businessType: selectedBusinessType,
      });
      setLoading(false);
    } catch (cause) {
      if (generation !== searchGeneration.current) return;
      setError(cause instanceof Error ? cause.message : '공고 목록을 불러오지 못했습니다.');
      setLoading(false);
    }
  }

  useEffect(() => {
    const saved = previousNotices();
    const timer = window.setTimeout(() => void initialize(saved?.query ?? '', saved?.page ?? 0, saved?.businessType ?? 'all', saved?.status ?? 'all'), 0);
    return () => { window.clearTimeout(timer); searchGeneration.current += 1; };
  }, []);

  function noticeStatus(noticeId: string): OverallStatus {
    return (notices.find((notice) => notice.id === noticeId)?.qualification_status ?? 'unreviewed') as OverallStatus;
  }
  const existingCaseByNotice = useMemo(
    () => new Map(notices.filter((row) => row.current_case_id).map((row) => [row.id, row.current_case_id as string])),
    [notices],
  );
  const businessTypeOptions = Object.keys(BUSINESS_TYPE_LABEL);
  const pageRange = noticePageRange(noticeTotal, pageIndex);
  const activeNotices = notices.filter((row) => row.qualification_status !== 'core_unmet');
  const rejectedNotices = notices.filter((row) => row.qualification_status === 'core_unmet');
  const emptyReason = notices.length === 0 ? 'no-result' : rejectedNotices.length > 0 ? 'only-rejected' : 'filtered-out';
  const rejectedOpen = showRejected;
  const profile = productProfileCoverage(company);
  const missingProfile = profile.missing.map((area) => area.label);
  const profileReady = Boolean(company) && missingProfile.length === 0;
  const counts = statusCounts;
  const unknownTotal = statusCounts.needs_review;
  const firstUnknownCase = notices.find((row) => row.qualification_status === 'needs_review' && row.current_case_id);
  const quickTiles: QuickTile[] = [
    { label: '전체', value: company ? Object.values(statusCounts).reduce((sum, count) => sum + count, 0) : noticeTotal, icon: LayoutGrid, filter: 'all' },
    { label: '핵심 요건 충족', value: counts.core_met, icon: CheckCircle2, filter: 'core_met' },
    { label: '확인 필요', value: counts.needs_review, icon: CircleHelp, filter: 'needs_review' },
    { label: '핵심 요건 미충족', value: counts.core_unmet, icon: XCircle, filter: 'core_unmet' },
    { label: '미검토', value: counts.unreviewed, icon: FileCheck2, filter: 'unreviewed' },
  ];

  async function startReview(notice: BidNoticeSummary) {
    const existing = existingCaseByNotice.get(notice.id);
    if (existing) {
      router.push(`/qualification?caseId=${existing}`);
      return;
    }
    if (!company) {
      setError('먼저 사용할 회사 프로필이 필요합니다.');
      return;
    }

    setCreatingNoticeId(notice.id);
    setError('');
    try {
      /*
        목록에 없다고 없는 게 아니다. 목록은 상위 100건까지만 받아오므로
        그 밖에 있는 기존 검토 건을 놓치고 같은 공고로 Case를 또 만들 수 있다.
        만들기 직전에 이 공고만 다시 확인한다. (#131 리뷰)
      */
      const known = await findPreflightCasesByNotice(notice.id, company.id);
      const reusable = known.items.find((item) => item.current_version_number === notice.current_version);
      if (reusable) {
        router.push(`/qualification?caseId=${reusable.id}`);
        return;
      }
      const versions = await getNoticeVersions(notice.id);
      const current = versions.find((item) => item.is_current) ?? versions[0];
      if (!current) throw new Error('현재 공고 버전을 찾지 못했습니다.');
      const baseline = versions
        .filter((item) => item.version_number < current.version_number)
        .sort((a, b) => b.version_number - a.version_number)[0];
      const created = await createPreflightCaseWithCompany({
        notice_id: notice.id,
        company_id: company.id,
        baseline_version_number: baseline?.version_number,
        current_version_number: current.version_number,
        title: `${notice.bid_notice_no} 참가자격 검토`,
      });
      router.push(`/qualification?caseId=${created.id}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '검토 건 생성에 실패했습니다.');
    } finally {
      setCreatingNoticeId(null);
    }
  }

  return (
    <main className="bg-white text-[var(--product-body)]" aria-busy={loading}>
      <section className="border-b border-[var(--product-line)] bg-[linear-gradient(120deg,#e6eeff_0%,#f0ebff_48%,#e8f4ff_100%)]">
        <div className="app-shell-container pt-9 pb-10 md:pt-10 md:pb-12">
          {/*
            상자를 걷어낸다. 전에는 프로필 안내·검색·소개가 각각 상자여서 첫 화면에만 상자가 셋이었다.
            프로필 안내는 배경 위에 한 줄로 얹고, 소개는 아래 검색 상자 안으로 넣어 상자를 하나로 줄인다.
          */}
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[15px] text-[var(--product-body)]">
            <span className={profileReady ? 'text-emerald-700' : 'text-amber-700'}>{profileReady ? <CheckCircle2 className="size-[18px]" /> : <CircleHelp className="size-[18px]" />}</span>
            {/* 상태 한 줄이면 된다. 「채우면 걸러드립니다」 같은 설명은 링크가 이미 말한다. */}
            <strong className="font-bold">{company ? `${company.name} · 프로필 ${profile.filled}/${profile.total}` : '회사 프로필이 필요합니다'}</strong>
            {!profileReady && <NavigationLink href="/company" className="font-semibold text-[var(--product-accent-deep)]">채우면 걸러드립니다 →</NavigationLink>}
          </div>

          {/* 업무 시작점은 검색이다. 검색 상자 하나에 제목·입력·단계 띠를 모두 담아 첫 화면의 상자를 하나로 유지한다. */}
          <form onSubmit={(event) => { event.preventDefault(); void initialize(query, 0, businessTypeFilter, statusFilter); }} className="mt-4 overflow-hidden rounded-[24px] bg-white shadow-[0_16px_48px_rgba(55,70,120,0.12)]">
            <div className="flex flex-col gap-5 p-7 lg:flex-row lg:items-end lg:justify-between">
              <div className="min-w-0">
                <h1 className="text-[28px] font-extrabold leading-[1.25] tracking-[-0.04em] text-[var(--product-ink)]">검토할 공고를 바로 찾기</h1>
              </div>
              <div className="flex h-[56px] w-full items-center rounded-2xl border border-[var(--product-line)] bg-white px-4 focus-within:border-[var(--product-accent)] lg:max-w-[520px]">
                <Input value={query} onChange={(event) => setQuery(event.target.value)} className="h-auto flex-1 border-0 bg-transparent px-0 text-[15px] shadow-none focus-visible:ring-0" placeholder="공고번호 또는 공고명" aria-label="공고 검색" />
                <button type="submit" className="grid size-10 place-items-center rounded-full bg-[var(--product-accent)] text-white" aria-label="검색">{loading ? <LoaderCircle className="size-5 animate-spin" /> : <Search className="size-5" />}</button>
              </div>
            </div>
            {/*
              세 단계는 이름만 있으면 읽힌다. 단계마다 설명을 두 문장씩 붙였더니
              첫 화면이 「읽을거리」가 됐다. 무엇을 하는 서비스인지는 이름 셋이면 전달된다.
            */}
            <div className="flex flex-col gap-2 bg-[var(--product-accent-deep)] px-7 py-4 text-white lg:flex-row lg:items-center lg:justify-between">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {[
                  { icon: <Search className="size-[18px]" />, title: '공고 찾기' },
                  { icon: <FileCheck2 className="size-[18px]" />, title: '자격 판정' },
                  { icon: <RefreshCw className="size-[18px]" />, title: '변경 재검증' },
                ].map((step, index) => (
                  <span key={step.title} className="flex items-center gap-3">
                    {index > 0 && <ChevronRight className="size-4 text-white/40" />}
                    <span className="flex items-center gap-2 text-[15px] font-bold">{step.icon}{step.title}</span>
                  </span>
                ))}
              </div>
              {/* 「근거 없으면 판정하지 않는다」는 이 제품의 약속이라 한 줄로 남긴다. */}
              <span className="flex items-center gap-2 text-[13px] text-white/75"><ShieldCheck className="size-4" />근거가 없으면 판정하지 않고 「확인 필요」로 남깁니다</span>
            </div>
          </form>
        </div>

      </section>

      {/*
        이 사람이 나라장터를 놔두고 여기 오는 이유는 「우리 회사가 넣을 수 있는 공고」 하나다.
        그래서 검색 바로 다음이 그 목록이어야 한다. 전에는 화면 맨 아래에 있었다.
      */}
      <CachedNoticeMatches />

      <div className="app-shell-container pb-20 pt-2">
        {/* 실패를 알리기만 하면 사용자가 할 수 있는 일이 없다. 같은 조회를 바로 다시 걸 수 있게 둔다. */}
        {error && <div className="mb-6 flex flex-col gap-3 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 sm:flex-row sm:items-center sm:justify-between">
          <span className="flex items-start gap-2"><AlertCircle className="mt-0.5 size-4 shrink-0" />{error}</span>
          <Button type="button" variant="outline" size="sm" className="shrink-0 rounded-full border-rose-300 bg-white text-rose-700 hover:bg-rose-100" disabled={loading} onClick={() => void initialize(activeQuery, pageIndex, businessTypeFilter, statusFilter)}>
            {loading ? <LoaderCircle className="animate-spin" /> : <RefreshCw />} 다시 시도
          </Button>
        </div>}

        <section>
          {/* 눈썹(「공고 조회」)과 제목(「조회된 공고」)이 같은 말이었다. 제목만 남긴다. */}
          <h2 className="text-[28px] font-extrabold tracking-[-0.04em] text-[var(--product-ink)]">조회된 공고</h2>

          {/*
            타일은 이 목록의 검토 상태 필터다. 그래서 목록과 같은 섹션 안, 제목 바로 아래에 둔다.
            전에는 매칭 카드와 이 섹션 사이에 혼자 떠 있어서 어느 쪽에 속한 값인지 읽히지 않았다.
          */}
          <div className="mt-5 grid overflow-hidden rounded-[18px] border border-[var(--product-line)] bg-white grid-cols-2 sm:grid-cols-3 lg:grid-cols-6">
            {quickTiles.map(({ label, value, icon: Icon, filter }) => (
              <button key={label} type="button" aria-pressed={statusFilter === filter} onClick={() => void initialize(activeQuery, 0, businessTypeFilter, filter)} className={`border-b border-r border-[var(--product-line)] px-3 py-4 text-center transition-colors last:border-r-0 hover:bg-[var(--product-tint)] lg:border-b-0 ${statusFilter === filter ? 'bg-[#eef1ff]' : ''}`}>
                <Icon className={`mx-auto size-5 ${statusFilter === filter ? 'text-[var(--product-accent-deep)]' : 'text-[var(--product-accent)]'}`} />
                <span className="mt-1.5 block text-[13px] font-medium text-[var(--product-muted)]">{label}</span>
                <strong className="mt-0.5 block text-[21px] leading-7 text-[var(--product-ink)]">{value}</strong>
              </button>
            ))}
          </div>

          {/* 사업 유형은 라벨을 칩 줄 안에 넣어 한 줄로 끝낸다. 라벨만 따로 열을 차지할 값어치가 없다. */}
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="mr-0.5 text-[13px] font-bold text-[var(--product-muted)]">사업 유형</span>
            <button type="button" aria-pressed={businessTypeFilter === 'all'} onClick={() => { setBusinessTypeFilter('all'); void initialize(activeQuery, 0, 'all', statusFilter); }} className={`rounded-full border px-3.5 py-1.5 text-[13px] font-medium ${businessTypeFilter === 'all' ? 'border-[var(--product-accent)] bg-[#eef1ff] text-[var(--product-accent-deep)]' : 'border-[var(--product-line)] bg-white text-[var(--product-muted)]'}`}>전체</button>
            {businessTypeOptions.map((type) => <button key={type} type="button" aria-pressed={businessTypeFilter === type} onClick={() => { setBusinessTypeFilter(type); void initialize(activeQuery, 0, type, statusFilter); }} className={`rounded-full border px-3.5 py-1.5 text-[13px] font-medium ${businessTypeFilter === type ? 'border-[var(--product-accent)] bg-[#eef1ff] text-[var(--product-accent-deep)]' : 'border-[var(--product-line)] bg-white text-[var(--product-muted)]'}`}>{labelOf(BUSINESS_TYPE_LABEL, type)}</button>)}
          </div>

          {/* DL-007 — 「전체 공고」가 아니라 「검색으로 좁힌 결과의 상위 N건」이라는 사실은 남기되, 문장이 아니라 수치로 적는다. */}
          {loading && notices.length > 0 && (
            <output className="mt-3 block text-[13px] font-medium text-[var(--product-muted)]">
              ?? ??? ??? ???? ?? ??? ???? ????.
            </output>
          )}
          {!loading && <div className="mt-3 space-y-1 text-[13px] text-[var(--product-muted)]">
            <p>검색·필터 결과 전체 {noticeTotal.toLocaleString()}건 · 현재 페이지 {pageRange.start.toLocaleString()}–{pageRange.end.toLocaleString()}건 · 목록 표시 {activeNotices.length}건</p>
            <p>판정 상태별 건수는 선택한 회사의 전체 검색 결과 기준입니다.</p>
          </div>}

          {loading && notices.length === 0 ? <div className="grid min-h-64 place-items-center rounded-xl bg-slate-50" aria-label="?? ?? ???? ?"><div className="w-full space-y-3 px-5">{[0, 1, 2].map((index) => <div key={index} className="h-14 animate-pulse rounded-lg bg-slate-200" />)}</div></div> : activeNotices.length ? (
            /*
              카드 6장을 나열하면 한 화면에 6건뿐이라 서로 비교가 안 된다.
              같은 열을 세로로 세워 공고명·기관·유형·변경·검토 상태를 한눈에 견주게 한다.
              마감일 열은 목록 API(BidNoticeSummary)에 bid_closed_at이 없어 넣지 못했다.
              공고마다 버전을 따로 부르면 방금 없앤 N+1이 되살아난다 — 백엔드에 필드 추가를 요청해둔다.
            */
            <div className="mt-6 overflow-hidden rounded-[20px] border border-[var(--product-line)] bg-white">
              <div className="hidden grid-cols-[132px_minmax(0,1fr)_180px_96px_112px_128px] items-center gap-3 bg-[var(--product-tint)] px-5 py-3 text-[13px] font-bold text-[var(--product-muted)] lg:grid">
                <span>검토 상태</span><span>공고명 · 공고번호</span><span>공고기관</span><span>유형</span><span>변경</span><span className="text-right">조치</span>
              </div>
              {activeNotices.map((notice) => {
                const status = noticeStatus(notice.id);
                const changed = notice.current_version > 1;
                return (
                  <div key={notice.id} className="grid grid-cols-1 items-center gap-3 border-t border-[var(--product-line-2)] px-5 py-4 transition-colors hover:bg-[var(--product-tint)] lg:grid-cols-[132px_minmax(0,1fr)_180px_96px_112px_128px]">
                    <div><span className={`inline-block rounded-full border px-3 py-1 text-[13px] font-semibold ${OVERALL_STATUS_BADGE[status].className}`}>{OVERALL_STATUS_BADGE[status].label}</span></div>
                    <div className="min-w-0">
                      <strong className="block truncate text-[15px] font-bold text-[var(--product-ink)]">{notice.title}</strong>
                      <span className="mt-1 block text-[13px] text-[var(--product-muted)]">{notice.bid_notice_no}</span>
                    </div>
                    <span className="truncate text-[15px] text-[var(--product-muted)]">{notice.announcing_institution_name ?? '공고기관 미상'}</span>
                    <span className="text-[15px] text-[var(--product-muted)]">{labelOf(BUSINESS_TYPE_LABEL, notice.business_type)}</span>
                    {/*
                      차수가 1보다 크면 변경공고가 있었다는 뜻이다. 횟수는 백필 이력에 따라 달라질 수 있어 단정하지 않는다.
                      반대로 차수가 1이라고 원공고라고 말할 수는 없다 — 이력 백필(#129) 전에 수집된 공고는
                      변경이 있었어도 차수가 1로 남아 있다. 확인된 것만 쓴다.
                    */}
                    <span className={`text-[15px] ${changed ? 'font-semibold text-amber-700' : 'text-[var(--product-faint)]'}`}>{changed ? `변경 있음 · v${notice.current_version}` : '변경 여부 확인 전'}</span>
                    <div className="lg:text-right"><Button size="sm" onClick={() => void startReview(notice)} disabled={creatingNoticeId !== null} className="rounded-full px-4">{creatingNoticeId === notice.id ? <LoaderCircle className="animate-spin" /> : existingCaseByNotice.has(notice.id) ? '검토 보기' : '검토 시작'}<ArrowRight /></Button></div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="mt-7 rounded-[20px] border border-dashed border-[var(--product-line)] bg-[var(--product-tint)] px-6 py-16 text-center">
              <Search className="mx-auto size-8 text-[var(--product-faint)]" />
              {emptyReason === 'only-rejected' ? (
                <>
                  <p className="mt-3 font-semibold">현재 페이지의 {rejectedNotices.length}건은 모두 핵심 요건 미충족입니다.</p>
                  <p className="mt-1 text-sm text-[var(--product-muted)]">확인된 핵심 요건에 미충족 항목이 있어 아래에 접어 두었습니다. 법적 참가 불가 확정은 아닙니다.</p>
                  <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full" onClick={() => setShowRejected(true)}>아래에서 보기 ↓</Button>
                </>
              ) : emptyReason === 'filtered-out' ? (
                <>
                  <p className="mt-3 font-semibold">현재 페이지 {notices.length}건이 켜둔 필터에 걸려 표시되지 않았습니다.</p>
                  <p className="mt-1 text-sm text-[var(--product-muted)]">사업 유형 또는 검토 상태 필터를 해제하면 보입니다.</p>
                  <Button type="button" variant="outline" size="sm" className="mt-4 rounded-full" onClick={() => { setBusinessTypeFilter('all'); void initialize(activeQuery, 0, 'all', 'all'); }}>필터 모두 해제</Button>
                </>
              ) : (
                <>
                  <p className="mt-3 font-semibold">검색 결과가 없습니다.</p>
                  <p className="mt-1 text-sm text-[var(--product-muted)]">공고번호나 공고명을 다시 확인해 주세요. 공고번호는 차수(-00) 없이 입력합니다.</p>
                </>
              )}
            </div>
          )}
          {!loading && noticeTotal > 0 && (
            <nav aria-label="공고 페이지 이동" className="mt-6 flex flex-wrap items-center justify-center gap-4">
              <Button type="button" variant="outline" disabled={!pageRange.hasPrevious} onClick={() => void initialize(activeQuery, pageIndex - 1, businessTypeFilter, statusFilter)}>이전 페이지</Button>
              <span className="text-sm text-[var(--product-muted)]">{pageIndex + 1} / {pageRange.pageCount} 페이지</span>
              <Button type="button" variant="outline" disabled={!pageRange.hasNext} onClick={() => void initialize(activeQuery, pageIndex + 1, businessTypeFilter, statusFilter)}>다음 페이지</Button>
            </nav>
          )}
        </section>

        <section className="mt-12 overflow-hidden rounded-[22px] border border-[var(--product-line)] bg-[var(--product-tint)]">
          <button type="button" onClick={() => setShowRejected((value) => !value)} className="flex w-full items-center gap-4 px-6 py-5 text-left"><ChevronDown className={`size-5 transition-transform ${rejectedOpen ? 'rotate-180' : ''}`} /><div className="flex-1"><h3 className="text-[18px] font-bold text-[var(--product-ink)]">핵심 요건 미충족 공고{loading ? '' : ` ${rejectedNotices.length}건`}</h3><p className="mt-1 text-[15px] text-[var(--product-muted)]">숨기지 않습니다. 조건이나 회사 정보가 바뀌면 다시 검토할 수 있습니다.</p></div><span className="text-[15px] font-medium">{rejectedOpen ? '접기' : '펼치기'}</span></button>
          {rejectedOpen && <div className="border-t border-[var(--product-line)] bg-white px-6">{rejectedNotices.length ? rejectedNotices.map((notice) => {
            return <div key={notice.id} className="flex flex-col gap-3 border-b border-[var(--product-line-2)] py-5 last:border-b-0 md:flex-row md:items-center"><span className={`w-fit rounded-full border px-3 py-1 text-[13px] font-semibold ${OVERALL_STATUS_BADGE.core_unmet.className}`}>{OVERALL_STATUS_BADGE.core_unmet.label}</span><div className="min-w-0 flex-1"><strong className="block truncate text-[15px]">{notice.title}</strong>{/* 공고번호로 검색해 찾아온 행에 공고번호가 없으면 같은 건인지 확인할 수 없다. 판정 요약과 같이 적는다. */}
              <span className="mt-1 block text-[13px] text-[var(--product-muted)]">{notice.bid_notice_no}</span></div><button type="button" onClick={() => void startReview(notice)} className="text-left text-[15px] font-semibold text-[var(--product-accent-deep)]">근거 확인 →</button></div>;
          }) : <p className="py-8 text-center text-sm text-[var(--product-muted)]">{loading ? '판정 상태를 불러오는 중입니다.' : '현재 핵심 요건 미충족 공고가 없습니다.'}</p>}</div>}
        </section>

        {/*
          「공지사항」은 데이터 연결·근거 원칙·변경공고 세 줄이었는데, 첫 화면 소개 ①②③가
          같은 말을 이미 한다. 두 번 말하지 않고 지운다. 확인 필요 안내만 전체 폭으로 남긴다.
        */}
        <section className="mt-12">
          <aside className="rounded-[22px] bg-[var(--product-accent-deep)] p-7 text-white"><div className="flex items-start justify-between gap-3"><div><p className="text-[13px] font-semibold text-white/65">확인 필요</p><h2 className="mt-1 text-[28px] font-extrabold">확인이 필요한 공고</h2></div><strong className="text-[28px]">{loading ? '—' : unknownTotal}</strong></div><p className="mt-3 text-[15px] leading-6 text-white/75">정보가 부족한 항목은 미달로 만들지 않고 확인 필요로 남깁니다.</p><div className="mt-6 space-y-3">{Object.entries(ASK_BACK_REASON_COPY).map(([key, reason]) => <div key={key} className="rounded-2xl bg-white/10 p-4"><span className="flex items-center gap-2 text-[15px] font-semibold">{reason.canAnswer ? <CircleHelp className="size-4" /> : <ShieldCheck className="size-4" />} {reason.label}</span><p className="mt-2 text-[13px] leading-5 text-white/65">{reason.description}</p></div>)}</div>{firstUnknownCase ? <NavigationLink href={`/ask-back?caseId=${firstUnknownCase.current_case_id}`} className="mt-6 inline-flex items-center gap-2 text-[15px] font-bold">확인 필요 항목 보기 <ArrowRight className="size-4" /></NavigationLink> : <p className="mt-6 text-[15px] text-white/65">{loading ? '판정 상태를 불러오는 중입니다' : '지금 답할 항목이 없습니다'}</p>}</aside>        </section>

        {/* 다 채운 사람에게 「모두 연결되어 있습니다」를 한 블록 크기로 알릴 이유가 없다. 빌 때만 띄운다. */}
        {missingProfile.length > 0 && <section className="mt-12 flex flex-col justify-between gap-5 rounded-[24px] border border-[#d9ddf8] bg-[#f2f4ff] px-8 py-7 md:flex-row md:items-center"><div><h2 className="text-[28px] font-extrabold tracking-[-0.035em] text-[var(--product-ink)]">채우면 판정이 더 정확해집니다</h2><p className="mt-2 text-[15px] text-[var(--product-muted)]">{missingProfile.join(' · ')} 영역이 아직 비어 있습니다.</p></div><div className="flex items-center gap-4"><span className="text-[15px] font-semibold">{profile.total}개 영역 중 {profile.filled}개 연결</span><NavigationLink href="/company" className={buttonVariants({ variant: 'outline', className: 'rounded-full border-[var(--product-accent)] bg-white text-[var(--product-accent-deep)]' })}>프로필 보완</NavigationLink></div></section>}
      </div>
    </main>
  );
}
