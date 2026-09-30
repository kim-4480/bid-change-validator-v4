'use client';

import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { GitCompareArrows, LoaderCircle } from 'lucide-react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { Button } from '@/components/ui/button';
import { ActionCard } from '@/components/copilot/action-card';
import { useActions } from '@/components/copilot/provider';
import { currentRevalidation, isLocked } from '@/lib/copilot-actions';
import { baselineVersion, currentVersion, useCaseWorkspace } from '@/lib/case-workspace';
import type { CanonicalRequirement as QualificationRequirement } from '@/lib/qualification-api';
import { diffCanonicalRequirements, sameRequirementScope, sameStructuredRequirement } from '@/lib/requirement-diff';
import { CHANGE_TYPE_LABEL, labelOf, REQUIREMENT_TYPE_LABEL } from '@/lib/status-copy';

function formatDate(value: string | null | undefined) {
  if (!value) return '-';
  return new Date(value).toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' });
}

function money(value: number | null | undefined) {
  return value == null ? '-' : `${value.toLocaleString()} 원`;
}

/*
  구조화 값은 백엔드가 원문에서 뽑아낸 비교 대상이다.
  연산자(이상·포함 등)에 대응하는 한글 표가 아직 없으므로 값과 단위·기간만 적는다.
  「전라북도 이상」처럼 뜻을 지어내는 것보다 값만 보여주고 원문을 같이 두는 편이 정확하다.
*/
function requirementValue(requirement: QualificationRequirement) {
  if (requirement.value == null) return '값 없음';
  const unit = requirement.unit ? ` ${requirement.unit}` : '';
  const period = requirement.period_months ? ` · 최근 ${requirement.period_months}개월` : '';
  return `${requirement.value}${unit}${period}`;
}

function requirementChangeNote(before: QualificationRequirement | null, after: QualificationRequirement | null) {
  if (!before || !after || requirementValue(before) !== requirementValue(after)) return null;
  const notes = [];
  if (before.operator !== after.operator) notes.push('조건');
  if (!sameRequirementScope(before.scope, after.scope)) notes.push('범위');
  return notes.length ? `${notes.join('·')} 변경` : '구조 변경';
}

/** 재검증 결과 한 줄의 한쪽 차수. 요건이 없으면 왜 없는지를 적는다. */
function RequirementSide({ label, requirement, missing }: { label: string; requirement: QualificationRequirement | null; missing: string }) {
  return (
    <div className="rounded-[14px] border border-[#eef0f4] bg-[#fafbfc] px-4 py-3">
      <span className="text-[13px] font-semibold text-[var(--product-muted)]">{label}</span>
      {requirement ? (
        <>
          <p className="mt-1.5 text-[15px] leading-6 text-[var(--product-ink)]">{requirement.raw}</p>
          <p className="mt-2 text-[13px] text-[var(--product-muted)]">구조화 값 · {requirementValue(requirement)}</p>
        </>
      ) : (
        <p className="mt-1.5 text-[15px] leading-6 text-[var(--product-muted)]">{missing}</p>
      )}
    </div>
  );
}

export default function ChangesPage() {
  const caseId = useSearchParams().get('caseId');
  return <ChangesWorkspace key={caseId} caseId={caseId} />;
}

function ChangesWorkspace({ caseId }: { caseId: string | null }) {
  const { workspace, error: loadError, reload } = useCaseWorkspace(caseId);
  const { controller, action } = useActions(caseId ?? '');
  const result = currentRevalidation(action.result, {
    caseId: caseId ?? '', baselineAnalysisId: workspace?.baselineAnalysis?.id,
    currentAnalysisId: workspace?.currentAnalysis?.id, judgmentId: workspace?.displayJudgment?.id,
  });
  const hasPastResult = Boolean(action.result && 'revalidated_keys' in action.result && !result);
  const busy = isLocked(action);
  useEffect(() => {
    if (action.stage === 'COMPLETED') void reload();
  }, [action.stage, action.result?.result_judgment_run_id, reload]);

  const noticeComparison = useMemo(() => {
    if (!workspace) return [];
    const base = baselineVersion(workspace);
    if (!base) return [];
    const current = currentVersion(workspace);
    return [
      { key: 'bid-closed-at', label: '입찰서 제출마감', before: formatDate(base.bid_closed_at), after: formatDate(current.bid_closed_at) },
      { key: 'estimated-price', label: '추정가격', before: money(base.estimated_price), after: money(current.estimated_price) },
      { key: 'allocated-budget', label: '배정예산', before: money(base.allocated_budget), after: money(current.allocated_budget) },
      { key: 'contract-method', label: '계약방법', before: base.contract_method ?? '-', after: current.contract_method ?? '-' },
      { key: 'document-count', label: '첨부문서 수', before: `${base.documents.length}종`, after: `${current.documents.length}종` },
    ].map((row) => ({ ...row, changed: row.before !== row.after, changeNote: null as string | null }));
  }, [workspace]);

  const analyzedChanges = useMemo(() => {
    if (result) return result.changes;
    const baseline = workspace?.baselineAnalysisDetail;
    const current = workspace?.currentAnalysisDetail;
    if (!baseline || !current) return [];
    return diffCanonicalRequirements(baseline.requirements, current.requirements);
  }, [result, workspace?.baselineAnalysisDetail, workspace?.currentAnalysisDetail]);

  const comparison = useMemo(() => [
    ...noticeComparison,
    ...analyzedChanges
      .filter((item) => (
        item.change_type !== 'UNCHANGED'
        && (!item.baseline || !item.current || !sameStructuredRequirement(item.baseline, item.current))
      ))
      .map((item) => {
        const requirement = item.current ?? item.baseline;
        return {
          key: `requirement:${item.identity}`,
          label: `자격요건 · ${requirement ? labelOf(REQUIREMENT_TYPE_LABEL, requirement.type) : '유형 확인 필요'}`,
          before: item.baseline ? requirementValue(item.baseline) : '없음',
          after: item.current ? requirementValue(item.current) : '없음',
          changed: true,
          changeNote: requirementChangeNote(item.baseline, item.current),
        };
      }),
  ], [noticeComparison, analyzedChanges]);

  /*
    요건 행의 펼침 상태. 기본값은 행마다 다르다(구조화 값이 바뀐 것만 펼쳐 둔다).
    그래서 상태에는 「사용자가 직접 뒤집은 행」만 담고, 나머지는 렌더할 때 기본값을 쓴다.
    전부 state로 들고 있으면 결과가 새로 오는 순간 기본값을 다시 계산해 넣어야 한다.
  */
  const [toggledRows, setToggledRows] = useState<Record<string, boolean>>({});

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container py-12">
    <ActionCard caseId={caseId} />
    <p role="alert">{loadError || '검토 데이터를 불러오고 있습니다.'}</p>
    {loadError && <Button variant="outline" onClick={() => void reload()}>화면 정보 다시 조회</Button>}
  </main>;

  const baseline = baselineVersion(workspace);
  const canRevalidate = Boolean(workspace.sourceJudgment && workspace.baselineAnalysis && workspace.currentAnalysis && baseline);
  /*
    조건은 넷인데 안내 문구가 하나면, 버튼이 회색일 때 무엇이 없는지 알 수 없다.
    실제로 원인을 찾으려고 코드를 열어야 했다. 빠진 것만 짚어서 말한다.

    기준 판정은 없을 때뿐 아니라 rule_version이 현재 판정 규칙과 다를 때도 버려진다
    (lib/case-workspace.ts의 judgmentMatchesAnalysis). 그래서 「없어서」가 아니라
    「현재 판정 규칙으로 다시」라고 쓴다 — 판정을 다시 돌리면 둘 다 풀린다.
  */
  const missingForRevalidation = [
    !baseline && '기준 차수',
    !workspace.baselineAnalysis && '기준 차수 분석',
    !workspace.currentAnalysis && '현재 차수 분석',
    !workspace.sourceJudgment && '기준 차수 판정',
  ].filter((item): item is string => typeof item === 'string');
  const affectedChanges = analyzedChanges.filter((item) => item.change_type !== 'UNCHANGED');
  const hasRequirementComparison = Boolean(workspace.baselineAnalysisDetail && workspace.currentAnalysisDetail);
  /*
    「영향 있는 변경」은 요건이 달라졌다는 뜻이고, 그중에는 글머리 기호나 법령 인용처럼
    원문만 바뀐 것도 섞인다. 구조화된 값이 실제로 달라진 것이 몇 건인지 따로 센다.
  */
  const structuredChangedCount = affectedChanges.filter(
    (item) => !item.baseline || !item.current || !sameStructuredRequirement(item.baseline, item.current),
  ).length;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="changes" />

        <ActionCard caseId={caseId} />
        {hasPastResult && <p className="mt-3 text-sm text-[var(--product-muted)]">이전 분석 기준의 재검증 기록은 현재 결과 집계에 포함하지 않습니다.</p>}
        {loadError && <section role="alert" className="mt-4 rounded-xl border p-4">
          <p>작업 상태는 위에 유지됩니다. 화면 정보 갱신에 실패하여 마지막 조회 결과를 표시합니다.</p>
          <Button variant="outline" onClick={() => void reload()}>화면 정보 다시 조회</Button>
        </section>}

        <section className="mt-8">
          <div className="flex items-baseline gap-3"><h2 className="text-[21px] font-extrabold tracking-[-0.035em]">공고 차수</h2><span className="text-[15px] text-[var(--product-muted)]">판정은 차수에 묶입니다</span></div>
          <div className="mt-3 grid gap-3 md:grid-cols-3">
            {workspace.versions.map((version) => <article key={version.id} className={`rounded-[20px] border px-5 py-[18px] ${version.version_number === workspace.caseItem.current_version_number ? 'border-[var(--product-accent)] bg-[#edeafb]' : 'border-[var(--product-line)] bg-white'}`}><div className="flex items-center gap-2"><strong className="text-[15px]">{version.version_number}차 {version.version_number === 1 ? '공고' : '변경'}</strong>{version.version_number === workspace.caseItem.current_version_number && <span className="rounded-full bg-white px-2 py-1 text-[12px] font-bold">현재 판정 기준</span>}</div><p className="mt-2 text-[13px] text-[var(--product-muted)]">{formatDate(version.changed_at ?? version.posted_at ?? version.collected_at)}</p><p className="mt-2 text-[15px]">{version.change_reason ?? (version.version_number === 1 ? '최초 공고' : '변경 사유 미기재')}</p></article>)}
          </div>
        </section>

        {!baseline ? (
          <section className="mt-8 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-12 text-center">
            <h2 className="text-[21px] font-extrabold tracking-[-0.03em]">아직 변경 이력이 없습니다</h2>
            <p className="mt-3 text-[15px] leading-6 text-[var(--product-muted)]">현재 검토 건은 최초 공고만 존재합니다. 변경공고가 수집되면 이전 차수와 현재 차수를 비교하고, 바뀐 자격조건만 다시 판정합니다.</p>
          </section>
        ) : (
          <>
            <section className="mt-8">{comparison.every(({ changed }) => !changed) && <p className="mt-2 text-[15px] text-[var(--product-muted)]">주요 공고 정보와 구조화된 자격요건에는 변경이 없습니다.</p>}
              <div className="flex items-baseline gap-3"><h2 className="text-[21px] font-extrabold tracking-[-0.035em]">기준 → 현재 대비</h2><span className="text-[15px] text-[var(--product-muted)]">나라장터 수집 값과 구조화된 자격요건을 비교합니다</span></div>
              <div className="mt-3 overflow-hidden rounded-[20px] border border-[#eef0f4]">
                <div className="grid grid-cols-[270px_minmax(0,1fr)_minmax(0,1.4fr)_220px] bg-[#f6f7f9] py-[13px] text-[13px] font-semibold text-[var(--product-muted)]"><div className="px-4">항목</div><div className="px-4">기준 차수</div><div className="px-4">현재 차수</div><div className="px-4">판정 영향</div></div>
                {comparison.map(({ key, label, before, after, changed, changeNote }) => {
                  return <div key={key} className="grid min-h-[54px] grid-cols-[270px_minmax(0,1fr)_minmax(0,1.4fr)_220px] items-center border-t border-[#eef0f4] text-[15px]"><div className="px-4 font-semibold">{label}</div><div className="px-4 text-[var(--product-muted)]">{before}</div><div className="px-4 font-semibold">{after}</div><div className="px-4"><span className={`rounded-full px-3 py-1 text-[13px] font-bold ${changed ? 'bg-[#fbf0dc] text-[#8a5a00]' : 'bg-[#f6f7f9]'}`}>{changed ? '변경됨' : '변경 없음'}</span>{changeNote && <span className="ml-2 text-[12px] text-[var(--product-muted)]">{changeNote}</span>}</div></div>;
                })}
              </div>
            </section>

            <section className="mt-8 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
              <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between"><div><h2 className="text-[18px] font-bold">변경공고로 다시 판정할 항목</h2><p className="mt-2 text-[15px] text-[var(--product-muted)]">변경된 참가자격 요건 전체를 비교해 재검증합니다. 제안을 확인한 뒤 실행하며, 일부 요건만 선택하거나 제외할 수 없습니다.</p></div><Button onClick={() => void controller.propose(caseId, true)} disabled={!canRevalidate || busy || Boolean(loadError)} className="rounded-full">{busy ? <LoaderCircle className="animate-spin" /> : <GitCompareArrows />} 전체 변경 요건 재검증 제안</Button></div>
              {!canRevalidate && <p className="mt-4 text-[13px] leading-[1.75] text-[var(--product-muted)]"><strong className="text-[var(--product-body)]">{missingForRevalidation.join(' · ')}</strong>이 준비되지 않아 실행할 수 없습니다. 참가자격 검토 화면에서 다시 검토하면 기준 차수까지 현재 판정 규칙으로 함께 분석·판정합니다.</p>}
              {hasRequirementComparison && <div className="mt-5"><div className="mb-3 text-[15px]">영향 있는 변경 <strong>{affectedChanges.length}건</strong>{result && <> · 다시 판정 <strong>{result.revalidated_keys.length}건</strong></>} · 구조화 값이 바뀐 것 <strong>{structuredChangedCount}건</strong></div>{affectedChanges.length ? <div className="overflow-hidden rounded-[18px] border border-[#eef0f4]">{affectedChanges.map((item) => {
                // 재검증 결과가 양쪽 차수의 요건을 그대로 담아 온다. 따로 조회해 이어붙이지 않는다.
                const before = item.baseline;
                const after = item.current;
                const typeCode = after?.type ?? before?.type ?? null;
                // 양쪽이 다 있을 때만 견줄 수 있다. 신설·삭제는 견줄 상대가 없다.
                const comparable = Boolean(before && after);
                const sameStructured = sameStructuredRequirement(before, after);
                /*
                  기본은 접어 둔다. 다만 구조화 값이 바뀐 행은 펼쳐 둔다 —
                  이 화면에서 사람이 실제로 읽어야 하는 것이 그 행이기 때문이다.
                  신설·삭제(견줄 상대가 없는 행)도 마찬가지로 펼친다.
                */
                const openByDefault = !comparable || !sameStructured;
                const open = toggledRows[item.identity] ?? openByDefault;
                // 접힌 상태에서도 무엇이 어떻게 바뀌었는지는 한 줄로 읽히게 한다.
                const beforeValue = before ? requirementValue(before) : null;
                const afterValue = after ? requirementValue(after) : null;
                const summary = beforeValue && afterValue
                  ? (beforeValue === afterValue ? beforeValue : `${beforeValue} → ${afterValue}`)
                  : (afterValue ?? beforeValue ?? '구조화 값을 찾지 못했습니다');
                return (
                  <div key={item.identity} className="border-t border-[#eef0f4] first:border-t-0">
                    <button
                      type="button"
                      aria-expanded={open}
                      onClick={() => setToggledRows((previous) => ({ ...previous, [item.identity]: !open }))}
                      className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-[#fafbfc]"
                    >
                      <span aria-hidden className={`mt-0.5 text-[13px] text-[var(--product-muted)] transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-2">
                          {/* 요건 유형을 못 찾으면 내부 키라도 보여준다. 빈 칸보다는 낫고, 못 찾았다는 사실도 드러난다. */}
                          <strong className="text-[15px]">{typeCode ? labelOf(REQUIREMENT_TYPE_LABEL, typeCode) : (item.current_key ?? item.baseline_key ?? item.identity)}</strong>
                          <span className="rounded-full bg-[#fbf0dc] px-2.5 py-0.5 text-[13px] font-bold text-[#8a5a00]">{CHANGE_TYPE_LABEL[item.change_type]}</span>
                          {comparable && (sameStructured
                            ? <span className="rounded-full bg-[#f6f7f9] px-2.5 py-0.5 text-[13px] font-semibold text-[var(--product-muted)]">구조화 값 동일 · 원문 차이 있음</span>
                            : <span className="rounded-full bg-[#fbe9e9] px-2.5 py-0.5 text-[13px] font-bold text-[#9a2b2b]">구조화 값 변경</span>)}
                        </span>
                        <span className="mt-1 block truncate text-[13px] text-[var(--product-muted)]">{summary}</span>
                      </span>
                      <span className="mt-0.5 shrink-0 text-[13px] text-[var(--product-muted)]">{open ? '접기' : '원문 보기'}</span>
                    </button>
                    {open && (
                      <div className="grid gap-2 px-4 pb-4 lg:grid-cols-2">
                        <RequirementSide label="기준 차수" requirement={before} missing="기준 차수에는 없던 요건입니다." />
                        <RequirementSide label="현재 차수" requirement={after} missing="현재 차수에서 빠졌습니다." />
                      </div>
                    )}
                  </div>
                );
              })}</div> : <p className="rounded-[18px] border border-dashed border-[#eef0f4] px-4 py-6 text-center text-[15px] text-[var(--product-muted)]">자격조건에 영향 있는 변경이 없습니다. 기존 판정이 그대로 유지됩니다.</p>}</div>}            </section>
          </>
        )}

        <section className="mt-8 rounded-[20px] border border-[var(--product-line)] bg-[var(--product-tint)] p-5 text-[15px] leading-6 text-[var(--product-muted)]">
          <strong className="text-[var(--product-ink)]">현재 판정 반영 기준</strong><br />공고 값 변경은 나라장터 수집 값끼리 비교하고, 자격 판정 영향은 백엔드의 자격조건 비교와 다시 판정한 결과를 기준으로 표시합니다.
      </section>
      </div>
    </main>
  );
}
