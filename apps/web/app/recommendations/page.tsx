'use client';

import { useEffect, useMemo, useState } from 'react';
import { ArrowUpRight, BrainCircuit, RefreshCw, ShieldCheck } from 'lucide-react';
import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { listCompanies } from '@/lib/qualification-api';
import { listNoticeMatches, type NoticeMatch } from '@/lib/notice-matching-api';
import {
  listMlRecommendations, mlEndpointConfigured, safeRecommendationEvidenceHref,
  type MlRecommendation,
} from '@/lib/ml-recommendation-api';

type RecommendationState = {
  loading: boolean;
  companyName: string | null;
  matches: NoticeMatch[];
  ml: MlRecommendation[];
  mlUnavailable: boolean;
  mlError: string | null;
  matchingError: string | null;
  error: string | null;
};

const INITIAL: RecommendationState = {
  loading: true, companyName: null, matches: [], ml: [],
  mlUnavailable: false, mlError: null, matchingError: null, error: null,
};

const QUALIFICATION_LABEL: Record<NoticeMatch['overall_status'], string> = {
  eligible: '기존 자격판정: 충족',
  ineligible: '기존 자격판정: 미충족',
  insufficient_data: '기존 자격판정: 확인 필요',
};

function describeFailure(error: unknown) {
  return error instanceof Error ? error.message : '연결을 확인한 뒤 다시 시도해 주세요.';
}

export default function RecommendationsPage() {
  const [state, setState] = useState<RecommendationState>(INITIAL);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const companies = await listCompanies();
        if (!mounted) return;
        const company = companies[0];
        if (!company) {
          setState({ ...INITIAL, loading: false, error: '추천을 조회하려면 먼저 회사 프로필을 등록해 주세요.' });
          return;
        }
        const [matches, ml] = await Promise.allSettled([
          listNoticeMatches(company.id, 50),
          listMlRecommendations(company.id),
        ]);
        if (!mounted) return;
        const mlResult = ml.status === 'fulfilled' ? ml.value : null;
        setState({
          loading: false, companyName: company.name,
          matches: matches.status === 'fulfilled' ? matches.value.items : [],
          ml: mlResult?.items ?? [],
          mlUnavailable: !mlEndpointConfigured(),
          mlError: ml.status === 'rejected' ? describeFailure(ml.reason) : null,
          matchingError: matches.status === 'rejected' ? describeFailure(matches.reason) : null,
          error: null,
        });
      } catch (error) {
        if (mounted) setState({ ...INITIAL, loading: false, error: describeFailure(error) });
      }
    }
    void load();
    return () => { mounted = false; };
  }, [attempt]);

  const matchingByNotice = useMemo(
    () => new Map(state.matches.map((match) => [match.notice_id, match])),
    [state.matches],
  );
  const ranked = useMemo(() => [...state.ml].sort((left, right) => left.rank - right.rank), [state.ml]);

  function retry() {
    setState(INITIAL);
    setAttempt((value) => value + 1);
  }

  return (
    <main className="app-shell-container min-w-0 py-8 pb-20 sm:py-12">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-blue-700">
            <BrainCircuit size={17} aria-hidden="true" /> ML RECOMMENDATIONS
          </p>
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-[var(--product-ink)] sm:text-3xl">입찰 공고 추천</h1>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--product-muted)]">
            추천 순위와 점수는 공고의 업무 연관성을 나타냅니다. 참가자격 충족 여부는 별도의 규칙 기반 판정에서 확인해야 합니다.
          </p>
        </div>
        <Button type="button" variant="outline" disabled={state.loading} onClick={retry}>
          <RefreshCw size={16} aria-hidden="true" /> 새로고침
        </Button>
      </div>

      {state.loading ? (
        <output className="block mt-8 rounded-xl border bg-white p-5 text-sm">추천 및 기존 판정 결과를 확인하고 있습니다…</output>
      ) : state.error ? (
        <div role="alert" className="mt-8 rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
          {state.error} <NavigationLink href="/company" className="ml-2 underline">회사 프로필 이동</NavigationLink>
        </div>
      ) : (
        <>
          <section aria-labelledby="ml-heading" className="mt-8 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="ml-heading" className="text-lg font-bold">ML 추천 순위</h2>
              {process.env.NEXT_PUBLIC_ML_E2E_MOCK === 'true' && (
                <span className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-bold text-amber-900">
                  MOCK · 실제 모델 결과 아님
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-[var(--product-muted)]">조회 회사: {state.companyName}</p>
            {state.mlUnavailable ? (
              <output className="block mt-5 rounded-xl border border-dashed bg-slate-50 p-5 text-sm leading-6">
                ML 추천 API 계약 및 모델 학습 결과가 아직 연결되지 않았습니다. 점수나 모델 버전을 임의로 표시하지 않습니다.
                기존 자격판정 기반 공고 목록은 아래에서 별도로 조회할 수 있습니다.
              </output>
            ) : state.mlError ? (
              <p role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{state.mlError}</p>
            ) : ranked.length === 0 ? (
              <p className="mt-5 rounded-xl border bg-slate-50 p-5 text-sm">현재 표시할 ML 추천 결과가 없습니다.</p>
            ) : (
              <ol className="mt-5 space-y-4">
                {ranked.map((item) => {
                  const evidenceHref = safeRecommendationEvidenceHref(item.evidence_href);
                  const match = matchingByNotice.get(item.notice_id);
                  return (
                    <li key={item.notice_id} className="min-w-0 rounded-xl border border-slate-200 p-4 sm:p-5">
                      <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                          <p className="text-xs font-semibold text-blue-700">#{item.rank} 추천 · {item.bid_notice_no}</p>
                          <h3 className="mt-2 break-words text-base font-bold text-slate-900">{item.title}</h3>
                          <p className="mt-2 text-xs text-slate-600">모델 버전: {item.model_version}</p>
                        </div>
                        <div className="rounded-xl bg-blue-50 px-4 py-3 text-center">
                          <p className="text-xl font-bold text-blue-800">{Math.round(item.relevance_score * 100)}%</p>
                          <p className="text-xs text-blue-700">연관성 점수</p>
                        </div>
                      </div>
                      <ul className="mt-4 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-700">
                        {item.reasons.map((reason, index) => <li key={index}>{reason}</li>)}
                      </ul>
                      <div className="mt-4 flex flex-wrap items-center gap-3 border-t pt-4 text-xs">
                        <span className="flex items-center gap-1 font-semibold text-slate-700">
                          <ShieldCheck size={15} aria-hidden="true" />
                          {match ? QUALIFICATION_LABEL[match.overall_status] : '자격판정 별도 확인 필요'}
                        </span>
                        {evidenceHref && (
                          <a href={evidenceHref} target="_blank" rel="noopener noreferrer"
                            className="flex items-center gap-1 font-semibold text-blue-700">
                            추천 근거 원문 열기 <ArrowUpRight size={14} aria-hidden="true" />
                          </a>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ol>
            )}
          </section>

          <section aria-labelledby="qualification-matches-heading" className="mt-8 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
            <h2 id="qualification-matches-heading" className="text-lg font-bold">기존 자격판정 기반 공고</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--product-muted)]">
              ML 추천과 별개로 이미 저장된 분석 결과만 표시합니다. 새로운 판정을 자동 실행하지 않습니다.
            </p>
            {state.matchingError ? (
              <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{state.matchingError}</p>
            ) : state.matches.length ? (
              <ul className="mt-4 divide-y">
                {state.matches.map((match) => (
                  <li key={match.notice_id} className="flex flex-wrap justify-between gap-3 py-4 text-sm">
                    <span className="min-w-0 break-words font-medium">{match.title}</span>
                    <span className="text-xs font-semibold text-slate-600">{QUALIFICATION_LABEL[match.overall_status]}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-4 text-sm text-slate-600">저장된 자격판정 결과가 없습니다.</p>}
            <NavigationLink href="/notices" className="mt-5 inline-flex text-sm font-semibold text-blue-700 underline">
              공고 목록에서 직접 검토
            </NavigationLink>
          </section>
        </>
      )}
    </main>
  );
}