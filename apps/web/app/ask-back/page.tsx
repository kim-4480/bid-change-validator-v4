'use client';

import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { CaseHeader, CaseTabs } from '@/components/product/case-header';
import { EvidenceQuote } from '@/components/product/evidence-quote';
import type { EvidenceLocation } from '@/lib/qualification-api';
import { REQUIREMENT_TYPE_LABEL, labelOf } from '@/lib/status-copy';
import { Button, buttonVariants } from '@/components/ui/button';
import { ActionCard } from '@/components/copilot/action-card';
import { CopilotNavigationLink } from '@/components/copilot/navigation-link';
import { useActions } from '@/components/copilot/provider';
import { isLocked } from '@/lib/copilot-actions';

import { useCaseWorkspace, workspaceHref } from '@/lib/case-workspace';



export default function AskBackPage() {
  const caseId = useSearchParams().get('caseId');
  return <AskBackWorkspace key={caseId} caseId={caseId} />;
}

function AskBackWorkspace({ caseId }: { caseId: string | null }) {
  const { workspace, error: loadError, reload } = useCaseWorkspace(caseId);
  const { controller, action } = useActions(caseId ?? '');
  useEffect(() => {
    if (action.stage === 'COMPLETED') void reload();
  }, [action.stage, action.result?.result_judgment_run_id, reload]);
  const [skipped, setSkipped] = useState<Set<string>>(new Set());
  const [showSkipped, setShowSkipped] = useState(false);

  const allQuestions = workspace?.questions ?? [];
  const askable = allQuestions.filter((item) => item.askable);
  const unaskable = allQuestions.filter((item) => !item.askable);
  const totalJudgments = workspace?.displayJudgment?.judgments.length ?? 0;
  const totalUnknown = workspace?.displayJudgment?.judgments.filter((item) => item.status === 'UNKNOWN').length ?? 0;
  const resolvedCount = Math.max(totalJudgments - totalUnknown, 0);

  const askableVisible = askable.filter((item) => !skipped.has(item.requirement_key));
  const askableSkipped = askable.filter((item) => skipped.has(item.requirement_key));

  const evidenceByRequirement = useMemo(() => {
    const analysis = workspace?.currentAnalysisDetail;
    if (!analysis) return new Map<string, { key: string; quote: string; location: EvidenceLocation }>();
    const map = new Map<string, { key: string; quote: string; location: EvidenceLocation }>();
    for (const requirement of analysis.requirements) {
      const key = requirement.evidence_keys[0];
      const evidence = key ? analysis.evidence.find((item) => item.evidence_key === key) : null;
      if (evidence) map.set(requirement.requirement_key, { key, quote: evidence.quote, location: evidence.location });
    }
    return map;
  }, [workspace]);

  function skip(requirementKey: string) {
    setSkipped((current) => {
      const next = new Set(current);
      next.add(requirementKey);
      return next;
    });
  }

  function unskip(requirementKey: string) {
    setSkipped((current) => {
      const next = new Set(current);
      next.delete(requirementKey);
      return next;
    });
  }

  if (!caseId) return <main className="app-shell-container py-12">caseId가 필요합니다.</main>;
  if (!workspace) return <main className="app-shell-container py-12">
    <ActionCard caseId={caseId} />
    <p role="alert">{loadError || '검토 데이터를 불러오고 있습니다.'}</p>
    {loadError && <Button variant="outline" onClick={() => void reload()}>화면 정보 다시 조회</Button>}
  </main>;

  return (
    <main className="bg-white text-[var(--product-body)]">
      <div className="app-shell-container py-10">
        <CaseHeader workspace={workspace} />
        <CaseTabs caseId={workspace.caseItem.id} active="questions" />

        <ActionCard caseId={caseId} />
        {loadError && <section role="alert" className="mt-4 rounded-xl border p-4">
          <p>작업 상태는 위에 유지됩니다. 화면 정보 갱신에 실패하여 마지막 조회 결과를 표시합니다.</p>
          <Button variant="outline" onClick={() => void reload()}>화면 정보 다시 조회</Button>
        </section>}

        <section className="mt-5 rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 className="text-[19px] font-bold tracking-[-0.03em] text-[var(--product-ink)]">확인 필요 {totalUnknown}건 중 <span className="text-[var(--product-accent)]">답할 수 있는 것은 {askable.length}건</span>입니다</h2>
              <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">복합·예외·법적 요건은 사용자 답변만으로 판정하지 않습니다. 해당 조건은 원문 검토 대상으로 남겨둡니다.</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {/* 사용자가 직접 답한 개수가 아니라 자동 판정까지 포함한 값이라 「진행」이 아니라 「판정 완료」로 쓴다 */}
              {totalJudgments > 0 && <span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold text-[var(--product-muted)]">판정 완료 {resolvedCount}/{totalJudgments}</span>}
              <span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 판정 {askable.length}</span>
              <span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">물을 수 없음 {unaskable.length}</span>
            </div>
          </div>
        </section>

        <div className="mt-4 space-y-4">
          {askableVisible.map((question) => {
            const evidence = evidenceByRequirement.get(question.requirement_key);

            return (
              <section key={question.requirement_key} className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full bg-[#fbf0dc] px-3 py-1 text-[12px] font-bold text-[#8a5a00]">답하면 판정합니다</span>
                    <span className="text-[12.5px] text-[var(--product-muted)]">{labelOf(REQUIREMENT_TYPE_LABEL, question.requirement_type)}</span>
                  </div>
                  <button type="button" onClick={() => skip(question.requirement_key)} className="shrink-0 text-[12.5px] font-semibold text-[var(--product-muted)] underline underline-offset-2 hover:text-[var(--product-ink)]">이번 화면에서 건너뛰기</button>
                </div>
                <h3 className="mt-3 text-[19px] font-bold leading-8 tracking-[-0.03em] text-[var(--product-ink)]">{question.question}</h3>
                <p className="mt-3 text-[13.5px] text-[var(--product-muted)]">저장된 판정에서 사용자 답변을 요청한 요건입니다. 답변과 증빙 보유 여부를 선택한 뒤 제안 내용을 확인해 주세요.</p>
                {evidence && <div className="mt-4"><EvidenceQuote quote={evidence.quote} location={evidence.location} /></div>}

                <Button className="mt-4 rounded-full" disabled={isLocked(action) || Boolean(loadError)}
                  onClick={() => void controller.beginAnswer(caseId, question.requirement_key, workspace.displayJudgment?.id)}>
                  이 요건 답변 입력 · 아직 저장 안 함
                </Button>
              </section>
            );
          })}

          {askableSkipped.length > 0 && (
            <section className="rounded-[20px] border border-dashed border-[#eef0f4] bg-[#fafbfc] px-[26px] py-4">
              <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                <button type="button" onClick={() => setShowSkipped((v) => !v)} className="text-[13px] font-semibold text-[var(--product-muted)]">
                  건너뛴 항목 {askableSkipped.length}개 {showSkipped ? '접기 ▲' : '보기 ▼'}
                </button>
                {/* skipped는 화면 state라 저장되지 않는다. 저장된 상태로 오해하지 않도록 명시한다. */}
                <span className="text-[12px] text-[var(--product-faint)]">이 화면에서만 숨긴 상태로, 새로고침하면 다시 나타납니다</span>
              </div>
              {showSkipped && (
                <ul className="mt-3 space-y-2">
                  {askableSkipped.map((question) => (
                    <li key={question.requirement_key} className="flex items-center justify-between gap-3 text-[13px]">
                      <span className="text-[var(--product-ink)]">{question.question}</span>
                      <button type="button" onClick={() => unskip(question.requirement_key)} className="shrink-0 font-semibold text-[var(--product-accent-deep)]">다시 보기</button>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {unaskable.map((question) => {
            const evidence = evidenceByRequirement.get(question.requirement_key);
            return (
              <section key={question.requirement_key} className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-6">
                <div className="flex flex-wrap items-center gap-2"><span className="rounded-full bg-[#f6f7f9] px-3 py-1 text-[12px] font-bold">물을 수 없습니다</span></div>
                <h3 className="mt-3 text-[18px] font-bold">{question.raw_requirement}</h3>
                <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">{question.askability_reason}</p>
                {evidence && <div className="mt-4"><EvidenceQuote quote={evidence.quote} location={evidence.location} /></div>}
                {evidence && (
                  <CopilotNavigationLink caseId={workspace.caseItem.id} href={`${workspaceHref('/evidence', workspace.caseItem.id)}&evidence=${encodeURIComponent(evidence.key)}`} className={buttonVariants({ variant: 'outline', className: 'mt-4 rounded-full' })}>근거 원문에서 확인</CopilotNavigationLink>
                )}
              </section>
            );
          })}

          {totalUnknown === 0 && (
            <section className="rounded-[20px] border border-[#eef0f4] bg-white px-[26px] py-12 text-center">
              <h3 className="text-[19px] font-bold">{workspace.displayJudgment ? '지금 답할 확인 필요 항목이 없습니다' : '아직 분석과 판정이 필요합니다'}</h3>
              <p className="mt-2 text-[13.5px] text-[var(--product-muted)]">판정 결과에서 사용자 확인이 필요한 항목이 생기면 이 화면에 표시합니다</p>
              <CopilotNavigationLink caseId={workspace.caseItem.id} href={workspaceHref('/qualification', workspace.caseItem.id)} className={buttonVariants({ variant: 'outline', className: 'mt-5 rounded-full' })}>참가자격 검토로 돌아가기</CopilotNavigationLink>
            </section>
          )}
        </div>
      </div>
    </main>
  );
}
