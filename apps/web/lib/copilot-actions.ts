import { ApiError } from './api';
import { sendCopilotMessage, confirmCopilotAction, type ActionProposal, type CopilotChatResponse, type CopilotChatRequest, type ConfirmAction, type ConfirmActionResult, type ReadReceipt } from './copilot-api';
import { validateSources } from './copilot-conversation';

export type Execution = 'IDLE' | 'DRAFT' | 'PROPOSAL_READY' | 'CONFIRMING' | 'REFRESHING' | 'COMPLETED' | 'STALE' | 'FAILED' | 'OUTCOME_UNKNOWN' | 'DONE_REFRESH_FAILED' | 'AUTH_REQUIRED';
export type Draft = { requirement_key: string; label: string; satisfies_requirement: boolean | null; evidence_held: boolean | null; normalized_value: string; receipt: ReadReceipt };
export type ActionState = { stage: Execution; busy: boolean; externalBusy: boolean; revision: number; draft: Draft | null; proposal: ActionProposal | null; result: ConfirmActionResult | null; response: CopilotChatResponse | null; message: string };
const initial = (): ActionState => ({ stage: 'IDLE', busy: false, externalBusy: false, revision: 0, draft: null, proposal: null, result: null, response: null, message: '' });
export const isLocked = (state: ActionState) => state.busy || state.externalBusy || ['CONFIRMING', 'REFRESHING', 'OUTCOME_UNKNOWN', 'DONE_REFRESH_FAILED'].includes(state.stage);
const messageOf = (error: unknown) => error instanceof Error ? error.message : '처리를 확인하지 못했습니다.';
export function authenticationRejected(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401 &&
    ['AUTHENTICATION_REQUIRED', 'INVALID_SESSION'].includes(error.code);
}

// A past result may remain in memory, but must not be labelled as current.
export function currentRevalidation(result: ConfirmActionResult | null, context: {
  caseId: string; baselineAnalysisId?: string | null; currentAnalysisId?: string | null;
  judgmentId?: string | null;
}) {
  return result && 'revalidated_keys' in result && result.preflight_case_id === context.caseId &&
    result.baseline_analysis_run_id === context.baselineAnalysisId &&
    result.current_analysis_run_id === context.currentAnalysisId &&
    result.result_judgment_run_id === context.judgmentId ? result : null;
}

type Read = (request: CopilotChatRequest) => Promise<CopilotChatResponse>;
type Confirm = (request: ConfirmAction) => Promise<ConfirmActionResult>;

// A safe, non-running action may cross one native page navigation. In-flight
// writes still require a server execution ID and are deliberately not restored.
export class ActionController {
  private states = new Map<string, ActionState>();
  private listeners = new Set<() => void>();
  constructor(private read: Read = sendCopilotMessage,
    private write: Confirm = request => confirmCopilotAction(request, AbortSignal.timeout(30_000)),
    private refreshed: (caseId: string, response: CopilotChatResponse) => void = () => {}) {}
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
  get(caseId: string) {
    if (!this.states.has(caseId)) this.states.set(caseId, initial());
    return this.states.get(caseId)!;
  }
  private update(caseId: string, patch: Partial<ActionState>) {
    this.states.set(caseId, { ...this.get(caseId), ...patch });
    this.listeners.forEach(fn => fn());
  }
  snapshot(caseId: string): ActionState | null {
    const state = this.get(caseId);
    return isLocked(state) ? null : structuredClone(state);
  }
  restore(caseId: string, state: ActionState) {
    if (!caseId || isLocked(state)) return;
    const safeStages: Execution[] = ['IDLE', 'DRAFT', 'PROPOSAL_READY', 'COMPLETED', 'STALE', 'FAILED', 'AUTH_REQUIRED'];
    if (!safeStages.includes(state.stage)) return;
    this.states.set(caseId, { ...structuredClone(state), busy: false, externalBusy: false });
    this.listeners.forEach(fn => fn());
  }
  // A full review uses existing APIs, but shares the in-tab mutation lock.
  acquireReview(caseId: string) {
    const state = this.get(caseId);
    if (isLocked(state)) return false;
    this.update(caseId, { ...initial(), revision: state.revision + 1, externalBusy: true });
    return true;
  }
  releaseReview(caseId: string) { this.update(caseId, { externalBusy: false }); }
  private fail(caseId: string, error: unknown) {
    this.update(caseId, { busy: false, proposal: null, stage: authenticationRejected(error) ? 'AUTH_REQUIRED' : error instanceof ApiError && error.status === 409 ? 'STALE' : 'FAILED', message: messageOf(error) });
  }
  async beginAnswer(caseId: string, key: string, expectedJudgmentId?: string) {
    if (!caseId || isLocked(this.get(caseId))) return;
    const revision = this.get(caseId).revision + 1;
    this.update(caseId, { ...initial(), revision, busy: true });
    try {
      const response = await this.read({ case_id: caseId, message: '확인할 요건', intent: 'REQUIRED_CHECKS', requirement_key: key });
      if (this.get(caseId).revision !== revision) return;
      const state = response.product_state;
      const receipt = response.reply_context?.last_read_receipt;
      const question = state && 'questions' in state ? state.questions.find(q => q.requirement_key === key) : null;
      if (expectedJudgmentId && state && 'judgment_run_id' in state.provenance && state.provenance.judgment_run_id !== expectedJudgmentId) {
        this.update(caseId, { busy: false, stage: 'STALE', message: '판정 기준이 바뀌었습니다. 현재 결과를 다시 확인해 주세요.' }); return;
      }
      if (!question?.askable || !receipt || receipt.kind !== 'product' || receipt.provenance.case_id !== caseId) throw new Error('사용자 답변이 가능한 현재 요건이 아닙니다.');
      this.update(caseId, { busy: false, stage: 'DRAFT', draft: { requirement_key: key, label: question.question,
        satisfies_requirement: null, evidence_held: null, normalized_value: '', receipt } });
    } catch (error) { if (this.get(caseId).revision === revision) this.fail(caseId, error); }
  }
  edit(caseId: string, patch: Partial<Pick<Draft, 'satisfies_requirement' | 'evidence_held' | 'normalized_value'>>) {
    const state = this.get(caseId);
    if (!state.draft || isLocked(state)) return;
    this.update(caseId, { draft: { ...state.draft, ...patch }, proposal: null, stage: 'DRAFT', message: '', revision: state.revision + 1 });
  }
  cancel(caseId: string) {
    const state = this.get(caseId);
    if (isLocked(state)) return;
    this.update(caseId, { ...initial(), revision: state.revision + 1 });
  }
  adopt(caseId: string, proposal: ActionProposal) {
    if (isLocked(this.get(caseId)) || proposal.expected.case_id !== caseId) return;
    this.update(caseId, { ...initial(), revision: this.get(caseId).revision + 1, stage: 'PROPOSAL_READY', proposal: structuredClone(proposal) });
  }
  async propose(caseId: string, revalidate = false) {
    const state = this.get(caseId), draft = state.draft;
    if (!caseId || isLocked(state)) return;
    if (!revalidate && (!draft || draft.satisfies_requirement === null || draft.evidence_held === null)) {
      this.update(caseId, { message: '충족 여부와 증빙 보유 여부를 모두 선택해 주세요.' }); return;
    }
    const revision = state.revision + 1;
    this.update(caseId, { revision, busy: true, proposal: null, result: null, response: null, message: '' });
    try {
      const response = await this.read(revalidate
        ? { case_id: caseId, message: '전체 변경 요건 재검증해줘', intent: 'ACTION_REQUEST' }
        : { case_id: caseId, message: '적용해줘', intent: 'ACTION_REQUEST', requirement_key: draft!.requirement_key,
          user_input: { satisfies_requirement: draft!.satisfies_requirement!, evidence_held: draft!.evidence_held!, normalized_value: draft!.normalized_value.trim() || null, apply_to_profile: false },
          conversation_context: { context_revision: revision, visible_requirement_keys: [draft!.requirement_key], last_read_receipt: draft!.receipt } });
      if (this.get(caseId).revision !== revision) return;
      if (response.reply_context?.status === 'STALE_CONTEXT') { this.update(caseId, { busy: false, stage: 'STALE', message: response.answer }); return; }
      if (response.actions.length !== 1 || response.actions[0].expected.case_id !== caseId) throw new Error(response.answer || '실행 가능한 제안이 없습니다.');
      const proposal = response.actions[0];
      if ((revalidate && proposal.action_type !== 'REVALIDATE') || (!revalidate && (proposal.action_type !== 'ANSWER_REQUIREMENT' || proposal.requirement_key !== draft!.requirement_key))) throw new Error('요청한 작업과 제안이 다릅니다.');
      this.update(caseId, { busy: false, stage: 'PROPOSAL_READY', proposal, draft: revalidate ? null : draft });
    } catch (error) { if (this.get(caseId).revision === revision) this.fail(caseId, error); }
  }
  async confirm(caseId: string, confirmed: boolean) {
    const state = this.get(caseId);
    if (confirmed !== true || state.stage !== 'PROPOSAL_READY' || !state.proposal || isLocked(state)) return;
    const proposal = structuredClone(state.proposal);
    this.update(caseId, { stage: 'CONFIRMING', busy: true, message: '' });
    let result: ConfirmActionResult;
    try {
      result = await this.write({ confirmed: true, action: proposal });
      if (result.preflight_case_id !== caseId || !result.result_judgment_run_id) throw new Error('저장 응답의 대상 또는 결과를 확인하지 못했습니다.');
    } catch (error) {
      // Only explicit client/stale rejections establish that this attempt did not save.
      const auth = authenticationRejected(error);
      const rejected = auth || (error instanceof ApiError && [400, 404, 409, 422].includes(error.status));
      this.update(caseId, { busy: false, proposal: null, stage: auth ? 'AUTH_REQUIRED' : rejected ? (error instanceof ApiError && error.status === 409 ? 'STALE' : 'FAILED') : 'OUTCOME_UNKNOWN',
        message: auth ? '로그인이 만료되어 반영 요청이 거절됐습니다. 다시 로그인한 뒤 새 제안을 확인해 주세요.' : rejected ? messageOf(error) : '저장 성공 여부를 확인할 수 없습니다. 자동으로 다시 실행하지 않습니다. 현재 결과를 조회해 확인해 주세요.' });
      return;
    }
    this.update(caseId, { stage: 'REFRESHING', result, proposal: null });
    await this.refresh(caseId);
  }
  async refresh(caseId: string) {
    const state = this.get(caseId);
    if (!['REFRESHING', 'DONE_REFRESH_FAILED', 'OUTCOME_UNKNOWN'].includes(state.stage) || (state.busy && state.stage !== 'REFRESHING')) return;
    const unknown = state.stage === 'OUTCOME_UNKNOWN';
    this.update(caseId, { busy: true, stage: unknown ? 'OUTCOME_UNKNOWN' : 'REFRESHING' });
    try {
      const response = await this.read({ case_id: caseId, message: '현재 판정 결과', intent: 'QUALIFICATION_SUMMARY' });
      validateSources(response);
      const product = response.product_state;
      if (!product || !('judgment_run_id' in product.provenance) || product.provenance.case_id !== caseId) throw new Error('최신 판정을 확인하지 못했습니다.');
      if (!unknown && product.provenance.judgment_run_id !== state.result?.result_judgment_run_id) throw new Error('저장 결과와 현재 판정 기준이 다릅니다.');
      this.refreshed(caseId, response);
      this.update(caseId, { response, busy: false, stage: unknown ? 'OUTCOME_UNKNOWN' : 'COMPLETED',
        message: unknown ? '현재 판정을 조회했습니다. 이 조회만으로 이전 요청의 성공을 확정할 수 없어 재실행은 잠겨 있습니다.' : '반영 후 새 판정 결과를 확인했습니다.' });
    } catch {
      this.update(caseId, { busy: false, stage: unknown ? 'OUTCOME_UNKNOWN' : 'DONE_REFRESH_FAILED',
        message: unknown ? '저장 결과와 현재 상태를 확인하지 못했습니다. 자동 재실행하지 않습니다.' : '반영은 완료됐지만 새 판정을 불러오지 못했습니다. 결과 조회만 다시 시도해 주세요.' });
    }
  }
}
