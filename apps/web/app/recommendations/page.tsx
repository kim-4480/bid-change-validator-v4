'use client';

import { useEffect, useState } from 'react';
import { sharedQueryClient, invalidateSharedData } from '@/lib/shared-query-cache';
import { ArrowUpRight, BrainCircuit, RefreshCw, ShieldCheck } from 'lucide-react';
import { NavigationLink } from '@/components/navigation-link';
import { Button } from '@/components/ui/button';
import { getCurrentUser } from '@/lib/auth';
import { listCompanies } from '@/lib/qualification-api';
import { listNoticeMatches, type NoticeMatch } from '@/lib/notice-matching-api';
import {
  listMlRecommendations, usesTrainedModel,
  type MlRecommendationResponse,
} from '@/lib/ml-recommendation-api';

type RecommendationState = {
  loading: boolean;
  companyName: string | null;
  matches: NoticeMatch[];
  ml: MlRecommendationResponse | null;
  mlError: string | null;
  matchingError: string | null;
  error: string | null;
};

const INITIAL: RecommendationState = {
  loading: true, companyName: null, matches: [], ml: null,
  mlError: null, matchingError: null, error: null,
};

const QUALIFICATION_LABEL: Record<NoticeMatch['overall_status'], string> = {
  core_met: '핵심 요건: 충족',
  core_unmet: '핵심 요건: 미충족',
  needs_review: '핵심 요건: 확인 필요',
};

const ML_QUALIFICATION_LABEL = {
  core_met: '핵심 요건: 충족',
  core_unmet: '핵심 요건: 미충족',
  needs_review: '핵심 요건: 확인 필요',
  UNKNOWN: '규칙판정: 미검증',
  stale: '규칙판정: 이전 버전 (재검토 필요)',
} as const;

const SOURCE_LABEL = {
  local_lightgbm: 'LightGBM 모델',
  local_hf: 'Hugging Face 모델',
  remote_inference: '원격 추론 모델',
  lexical_fallback: '키워드 일치 기반 대체 순위',
} as const;

function describeFailure(error: unknown) {
  return error instanceof Error ? error.message : '연결을 확인하고 다시 시도해 주세요.';
}

export default function RecommendationsPage() {
  const [state, setState] = useState<RecommendationState>(() => sharedQueryClient().getQueryData<RecommendationState>(['view', 'recommendations']) ?? INITIAL);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [companies, user] = await Promise.all([listCompanies(), getCurrentUser()]);
        if (!active) return;
        const company = user?.company_id
          ? companies.find((item) => item.id === user.company_id)
          : companies[0];
        if (!company) {
          setState({ ...INITIAL, loading: false, error: '조회할 회사 프로필이 없습니다. 먼저 회사 프로필을 확인해 주세요.' });
          return;
        }
        const [matches, ml] = await Promise.allSettled([
          listNoticeMatches(company.id, 50),
          listMlRecommendations(company.id),
        ]);
        if (!active) return;
        const next: RecommendationState = {
          loading: false, companyName: company.name,
          matches: matches.status === 'fulfilled' ? matches.value.items : [],
          ml: ml.status === 'fulfilled' ? ml.value : null,
          mlError: ml.status === 'rejected' ? describeFailure(ml.reason) : null,
          matchingError: matches.status === 'rejected' ? describeFailure(matches.reason) : null,
          error: null,
        };
        sharedQueryClient().setQueryData(['view', 'recommendations'], next);
        setState(next);
      } catch (error) {
        if (active) setState({ ...INITIAL, loading: false, error: describeFailure(error) });
      }
    }
    void load();
    return () => { active = false; };
  }, [attempt]);

  function retry() {
    invalidateSharedData();
    setState(INITIAL);
    setAttempt((value) => value + 1);
  }

  const trained = state.ml ? usesTrainedModel(state.ml) : false;
  const ranked = [...(state.ml?.items ?? [])].sort((a, b) => a.rank - b.rank);
  const needsReview = [...(state.ml?.needs_review_items ?? [])].sort((a, b) => a.rank - b.rank);

  return (
    <main className="app-shell-container min-w-0 py-8 pb-20 sm:py-12">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-blue-700">
            <BrainCircuit size={17} aria-hidden="true" /> RECOMMENDATIONS
          </p>
          <h1 className="mt-2 text-2xl font-bold tracking-tight text-[var(--product-ink)] sm:text-3xl">입찰 공고 추천</h1>
          <p className="mt-3 max-w-3xl text-sm leading-7 text-[var(--product-muted)]">
            공고 연관성에 따른 추천 순위와 규칙 기반 참가자격 판정은 서로 다른 정보입니다.
            점수는 낙찰 또는 참가자격 확률이 아닙니다.
          </p>
        </div>
        <Button type="button" variant="outline" disabled={state.loading} onClick={retry}>
          <RefreshCw size={16} aria-hidden="true" /> 새로고침
        </Button>
      </div>

      {state.loading ? (
        <output className="mt-8 block space-y-4 rounded-xl border bg-white p-5 text-sm" aria-live="polite">
          {[0, 1, 2].map((index) => <div key={index} className="h-20 animate-pulse rounded-xl bg-slate-100" />)}
          추천 및 기존 자격판정 결과를 확인하고 있습니다.
        </output>
      ) : state.error ? (
        <div role="alert" className="mt-8 rounded-xl border border-red-200 bg-red-50 p-5 text-sm text-red-800">
          {state.error} <NavigationLink href="/company" className="ml-2 underline">회사 프로필로 이동</NavigationLink>
          <Button type="button" variant="outline" size="sm" className="ml-2" onClick={retry}>다시 시도</Button>
        </div>
      ) : (
        <>
          <section aria-labelledby="ml-heading" className="mt-8 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="ml-heading" className="text-lg font-bold">공고 연관성 순위</h2>
              {process.env.NEXT_PUBLIC_ML_E2E_MOCK === 'true' && (
                <span className="rounded-full border border-amber-300 bg-amber-50 px-3 py-1 text-xs font-bold text-amber-900">
                  MOCK · 실제 모델 결과 아님
                </span>
              )}
            </div>
            <p className="mt-1 text-sm text-[var(--product-muted)]">조회 회사: {state.companyName}</p>
            {state.mlError ? (
              <div role="alert" className="mt-5 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
                추천 조회에 실패했습니다: {state.mlError}
                <Button type="button" variant="outline" size="sm" className="ml-3" onClick={retry}>다시 시도</Button>
              </div>
            ) : state.ml ? (
              <>
                <p className="mt-4 text-sm font-semibold text-slate-800">
                  {trained ? '학습 모델 기반 연관성 순위' : '학습 모델 미적용 — 키워드 기반 대체 순위'}
                </p>
                <p className="mt-1 text-xs leading-6 text-slate-600">
                  처리 방식: {SOURCE_LABEL[state.ml.scoring_source]}
                  {trained && state.ml.model_version ? ' · 모델 ' + state.ml.model_version : ''}
                  {trained && state.ml.dataset_version ? ' · 데이터셋 ' + state.ml.dataset_version : ''}
                  {state.ml.fallback_reason ? ' · 대체 사유 ' + state.ml.fallback_reason : ''}
                </p>
                <p className="mt-2 text-xs text-slate-600">
                  마감·취소 여부를 확인한 현재 유효 후보 {state.ml.total_valid_candidates}건을 선별했습니다.
                  마감일이 없는 공고는 게시 후 40일을 임시 유효기간으로 표시합니다.
                </p>
                {ranked.length === 0 ? (
                  <p className="mt-5 rounded-xl border bg-slate-50 p-5 text-sm">검증된 핵심 요건 충족 추천 결과가 없습니다. 확인 필요 공고는 아래에 별도로 표시합니다.</p>
                ) : (
                  <ol className="mt-5 space-y-4">
                    {ranked.map((item) => {
                      return (
                        <li key={item.notice_id} className="min-w-0 rounded-xl border border-slate-200 p-4 sm:p-5">
                          <div className="flex flex-wrap items-start justify-between gap-4">
                            <div className="min-w-0 flex-1">
                              <p className="text-xs font-semibold text-blue-700">#{item.rank} · 공고 버전 {item.version_number}</p>
                              <h3 className="mt-2 break-words text-base font-bold text-slate-900">{item.title}</h3>
                              <p className="mt-2 text-sm leading-6 text-slate-700">{item.reason}</p>
                            </div>
                            <div className="rounded-xl bg-blue-50 px-4 py-3 text-center">
                              <p className="text-xl font-bold text-blue-800">{item.relevance_score.toFixed(3)}</p>
                              <p className="text-xs text-blue-700">연관성 점수 (확률 아님)</p>
                            </div>
                          </div>
                          <div className="mt-4 flex flex-wrap items-center gap-3 border-t pt-4 text-xs">
                            <span className="flex items-center gap-1 font-semibold text-slate-700">
                              <ShieldCheck size={15} aria-hidden="true" />
                              {ML_QUALIFICATION_LABEL[item.qualification_state]}
                            </span>
                            <NavigationLink href={'/notices/' + encodeURIComponent(item.notice_id)}
                              className="inline-flex items-center gap-1 font-semibold text-blue-700 underline">
                              공고 상세·첨부 원문 <ArrowUpRight size={14} aria-hidden="true" />
                            </NavigationLink>
                            <NavigationLink href="/qualification" className="font-semibold text-blue-700 underline">
                              자격판정 화면
                            </NavigationLink>
                          </div>
                          {item.qualification_reason && (
                            <p className="mt-2 text-xs text-slate-600">판정 근거 상태: {item.qualification_reason}</p>
                          )}
                          {item.deadline_source === 'assumed_40_days' && (
                            <p className="mt-2 text-xs text-amber-700">마감일 미상 · 게시 후 40일을 임시 기준으로 사용</p>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                )}
              </>
            ) : null}
          </section>
          {state.ml && (
            <section aria-labelledby="ml-review-heading" className="mt-8 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
              <h2 id="ml-review-heading" className="text-lg font-bold">확인 필요 공고</h2>
              <p className="mt-2 text-sm text-[var(--product-muted)]">
                자격요건이 아직 검증되지 않았거나 기업정보가 부족한 공고입니다. 핵심 요건 충족 추천에 포함하지 않습니다.
              </p>
              {needsReview.length === 0 ? (
                <p className="mt-4 text-sm text-slate-600">확인 필요 공고가 없습니다.</p>
              ) : (
                <ul className="mt-4 divide-y">
                  {needsReview.map((item) => (
                    <li key={item.notice_id} className="flex flex-wrap justify-between gap-3 py-4 text-sm">
                      <div className="min-w-0">
                        <NavigationLink href={'/notices/' + encodeURIComponent(item.notice_id)}
                          className="break-words font-medium text-blue-700 underline">{item.title}</NavigationLink>
                        <p className="mt-1 text-xs text-slate-600">{ML_QUALIFICATION_LABEL[item.qualification_state]}</p>
                        {item.deadline_source === 'assumed_40_days' && (
                          <p className="mt-1 text-xs text-amber-700">마감일 미상 · 임시 유효기간</p>
                        )}
                      </div>
                      <span className="text-xs text-slate-600">연관성 점수 {item.relevance_score.toFixed(3)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}
          <section aria-labelledby="qualification-matches-heading" className="mt-8 rounded-2xl border bg-white p-5 shadow-sm sm:p-7">
            <h2 id="qualification-matches-heading" className="text-lg font-bold">기존 규칙 기반 자격판정</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--product-muted)]">
              이미 저장된 분석 결과만 표시합니다. 이 화면에서 LLM 분석을 자동 실행하지 않습니다.
              최근 판정 결과 최대 50건으로 전체 공고의 적격 여부를 의미하지 않습니다.
            </p>
            {state.matchingError ? (
              <p role="alert" className="mt-4 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{state.matchingError}</p>
            ) : state.matches.length ? (
              <ul className="mt-4 divide-y">
                {state.matches.map((match) => (
                  <li key={match.notice_id} className="flex flex-wrap justify-between gap-3 py-4 text-sm">
                    <NavigationLink href={'/notices/' + encodeURIComponent(match.notice_id)}
                      className="min-w-0 break-words font-medium text-blue-700 underline">{match.title}</NavigationLink>
                    <span className="text-xs font-semibold text-slate-600">{QUALIFICATION_LABEL[match.overall_status]}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-4 text-sm text-slate-600">저장된 자격판정 결과가 없습니다.</p>}
            <NavigationLink href="/notices" className="mt-5 inline-flex text-sm font-semibold text-blue-700 underline">
              공고 전체 목록에서 직접 검색
            </NavigationLink>
          </section>
        </>
      )}
    </main>
  );
}
