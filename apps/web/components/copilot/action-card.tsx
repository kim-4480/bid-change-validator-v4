'use client';

import { useId } from 'react';
import { Button } from '@/components/ui/button';
import { useActions } from './provider';
import { CopilotNavigationLink } from './navigation-link';
import { isLocked } from '@/lib/copilot-actions';

/** One controller, two presentations. Panel summarizes; 03/06 explicitly execute. */
export function ActionCard({ caseId, compact = false }: { caseId: string; compact?: boolean }) {
  const { controller, action } = useActions(caseId);
  const id = useId();
  if (action.stage === 'IDLE' && !action.busy && !action.externalBusy && !action.message) return null;
  const locked = isLocked(action);
  const draft = action.draft;
  const isRevalidation = action.proposal?.action_type === 'REVALIDATE' || (action.result && 'revalidated_keys' in action.result);
  const path = isRevalidation ? '/changes' : '/ask-back';
  return <section className="copilot-action-card" aria-label="공통 작업 확인">
    <h3>{action.externalBusy ? '전체 검토 진행 중' : '반영 내용 확인'}</h3>
    <p className="copilot-action-note">이 검토 건에만 반영합니다. 회사 프로필은 변경하지 않습니다.</p>
    {compact && (draft || action.proposal) && <>
      <p>{draft?.label ?? action.proposal?.title}</p>
      <CopilotNavigationLink caseId={caseId} className="copilot-detail-link" href={`${path}?caseId=${encodeURIComponent(caseId)}`}>{isRevalidation ? '06 변경 화면' : '03 추가정보 화면'}에서 상세 확인 · 아직 실행 안 함</CopilotNavigationLink>
    </>}
    {!compact && draft && <>
      <p>{draft.label}</p>
      {(['satisfies_requirement', 'evidence_held'] as const).map(field => <label key={field} htmlFor={`${id}-${field}`}>
        {field === 'satisfies_requirement' ? '이 요건을 충족하나요?' : '증빙을 보유하고 있나요?'}
        <select id={`${id}-${field}`} disabled={locked} value={draft[field] === null ? '' : String(draft[field])}
          onChange={event => controller.edit(caseId, { [field]: event.target.value === '' ? null : event.target.value === 'true' })}>
          <option value="">선택해 주세요</option><option value="true">예</option><option value="false">아니요</option>
        </select>
      </label>)}
      <label htmlFor={`${id}-value`}>답변 값 (필요한 경우)<input id={`${id}-value`} maxLength={2000} value={draft.normalized_value} disabled={locked}
        onChange={event => controller.edit(caseId, { normalized_value: event.target.value })} /></label>
      <Button type="button" variant="outline" disabled={locked || draft.satisfies_requirement === null || draft.evidence_held === null}
        onClick={() => void controller.propose(caseId)}>반영 제안 받기 · 아직 저장 안 함</Button>
    </>}
    {!compact && action.proposal && <>
      <h4 className="font-semibold">{action.proposal.title}</h4><p>{action.proposal.consequences}</p>
      {action.proposal.action_type === 'REVALIDATE'
        ? <p>기준 v{action.proposal.expected.baseline.version_number} → 현재 v{action.proposal.expected.current.version_number}<br />범위: 변경된 참가자격 요건 전체. 특정 요건만 선택하거나 제외할 수 없습니다.</p>
        : <p>공고 v{action.proposal.expected.version_number} · 대상: {draft?.label ?? action.proposal.requirement_key}<br />충족: {action.proposal.user_input.satisfies_requirement ? '예' : '아니요'} · 증빙: {action.proposal.user_input.evidence_held ? '예' : '아니요'}<br />값: {action.proposal.user_input.normalized_value || '미입력'}</p>}
      <Button type="button" className="copilot-action-confirm" disabled={locked || action.stage !== 'PROPOSAL_READY'}
        onClick={() => void controller.confirm(caseId, true)}>내용 확인 후 실행</Button>
    </>}
    {(action.busy || action.externalBusy) && <output>{action.externalBusy ? '기존 전체 분석·판정이 진행 중입니다. 다른 반영 작업은 잠겨 있습니다.' : action.stage === 'CONFIRMING' ? '반영 중입니다…' : action.stage === 'REFRESHING' ? '새 판정을 조회하고 있습니다…' : '확인하고 있습니다…'}</output>}
    {action.message && <p role={['COMPLETED', 'DRAFT'].includes(action.stage) ? undefined : 'alert'}>{action.message}</p>}
    {action.response && <div><p className="copilot-action-note">작업 후 조회한 결과 · 아래 화면의 최신 판정과 기준이 다를 수 있습니다</p><p className="font-semibold">{action.response.presentation?.conclusion ?? action.response.answer}</p></div>}
    <div className="copilot-action-buttons">
      {['DONE_REFRESH_FAILED', 'OUTCOME_UNKNOWN'].includes(action.stage) && <Button type="button" variant="outline" disabled={action.busy}
        onClick={() => void controller.refresh(caseId)}>결과 조회만 다시 시도</Button>}
      {!locked && <Button type="button" variant="outline" onClick={() => controller.cancel(caseId)}>작업 닫기</Button>}
    </div>
    <p className="copilot-action-note">패널을 닫아도 진행 상태는 유지됩니다. 새로고침·탭 종료 후 실행 상태 복구는 지원하지 않습니다.</p>
  </section>;
}
