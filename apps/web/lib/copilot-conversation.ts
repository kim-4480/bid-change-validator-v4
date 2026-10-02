import { apiFetch, ApiError } from './api';
import { validateEnvelope } from './copilot-v31';
import type { CopilotChatRequest, CopilotChatResponse, CopilotIntent, ReplyContext } from './copilot-api';

export type Turn = { id: number; question: string; response?: CopilotChatResponse };
export type Conversation = { turns: Turn[]; busy: boolean; error: string; errorCode: string; focus: string | null; revision: number; reply?: ReplyContext; conversationId?: string; serverRevision?: number; targetId?: string };
const empty = (): Conversation => ({ turns: [], busy: false, error: '', errorCode: '', focus: null, revision: 0 });
type ConversationRequest = CopilotChatRequest & { semantic_processing?: boolean; document_processing?: boolean };
export type Transport = (request: ConversationRequest) => Promise<CopilotChatResponse>;
export type GuidedSelection = { jobId: string; questionId: string };
type FailedRead = { request: ConversationRequest; turnId: number };

async function sendConversationMessage(request: ConversationRequest): Promise<CopilotChatResponse> {
  const { semantic_processing, document_processing, ...payload } = request;
  const body: CopilotChatRequest = document_processing ? {
    ...payload,
    public_document_question: payload.public_document_question ?? payload.message,
    allow_external_processing: true,
  } : payload;
  const response = await apiFetch('/api/v1/copilot/chat', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(semantic_processing ? { 'X-Copilot-Semantic-Processing': 'true' } : {}),
    },
    body: JSON.stringify({ ...body, response_version: '3.1' }),
  });
  if (!response.ok) {
    const responseBody = (await response.json().catch(() => null)) as { error?: { message?: string; code?: string } } | null;
    throw new ApiError(responseBody?.error?.message ?? `요청에 실패했습니다. (${response.status})`,
      response.status, responseBody?.error?.code ?? 'HTTP_ERROR');
  }
  return response.json() as Promise<CopilotChatResponse>;
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort()
    .map(key => JSON.stringify(key) + ':' + canonical((value as Record<string, unknown>)[key])).join(',') + '}';
  return JSON.stringify(value);
}

function sameReadReceipt(a: ReplyContext['last_read_receipt'] | null | undefined, b: ReplyContext['last_read_receipt'] | null | undefined) {
  return Boolean(a && b && canonical(a) === canonical(b));
}

function conversationReply(next: ReplyContext | undefined, previous?: ReplyContext): ReplyContext | undefined {
  if (!next) return undefined;
  if (next.status === 'RESOLVED' && next.visible_requirement_keys.length === 0 &&
      previous?.visible_requirement_keys.length && sameReadReceipt(next.last_read_receipt, previous.last_read_receipt)) {
    // A manual-review/help turn can legitimately expose no targetable requirement.
    // Keep the last requirement list the user actually saw while Product Truth is
    // unchanged, so a later "첫 번째 조건" still refers to that visible list.
    return { ...next, visible_requirement_keys: [...previous.visible_requirement_keys] };
  }
  return next;
}

const compactQuestion = (text: string) => text.replace(/\s+/g, '').replace(/[?.!。？！]/g, '');

export function hasOrdinalReference(question: string) {
  return /(?:[+-]?\d+(?:\.\d+)?|첫|두|세|네|다섯|여섯|일곱|여덟|아홉|열)번째/.test(compactQuestion(question));
}

export function isCopilotHelpQuestion(question: string) {
  const text = compactQuestion(question);
  return ['물어볼수있는질문', '뭘물어볼', '무엇을물어볼', '어떻게써', '사용법', '쓸수있는기능', '할수있는기능']
    .some(term => text.includes(term)) || text.includes('그중에서지금할수있는것');
}

/**
 * E1 deliberately adds only high-confidence aliases. Broad semantic routing stays
 * in E2 so we can measure the value of meaning-based routing separately.
 */
export function inferE1Intent(question: string): CopilotIntent | undefined {
  const text = compactQuestion(question);
  const companySubject = ['우리', '저희', '당사'].some(term => text.includes(term));
  if (companySubject && ['참가할수', '참여할수', '넣어도돼', '넣을수', '지원할수']
      .some(term => text.includes(term))) return 'QUALIFICATION_SUMMARY';
  if (['무엇이바뀌', '뭐가바뀌', '바뀐내용', '달라진내용', '변경내용', '무슨차이', '어떤차이', '차이가뭐', '다른점', '비교해']
      .some(term => text.includes(term))) return 'CHANGED_NOTICE';
  return undefined;
}

export function copilotReadErrorMessage(error: unknown) {
  if (!(error instanceof ApiError)) return error instanceof Error ? error.message : '조회하지 못했습니다.';
  const messages: Record<string, string> = {
    CHANGED_NOTICE_REQUIRED: '변경사항을 비교하려면 비교할 이전 버전과 회사 기준이 필요합니다. 현재 공고의 버전과 선택한 회사를 확인해 주세요.',
    QUALIFICATION_ANALYSIS_REQUIRED: '비교할 공고 버전 중 분석이 준비되지 않은 버전이 있습니다. 분석이 완료된 뒤 다시 비교해 주세요.',
    BASELINE_JUDGMENT_REQUIRED: '이전 버전 기준의 회사 판정이 없어 회사 영향까지 비교할 수 없습니다. 이전 버전 판정을 먼저 확인해 주세요.',
    QUALIFICATION_ANALYSIS_FAILED: '비교에 필요한 공고 분석이 완료되지 않았습니다. 분석 상태를 확인해 주세요.',
    STALE_ACTION_CONTEXT: '공고·분석·판정 기준이 바뀌었습니다. 현재 결과를 다시 확인해 주세요.',
    DOCUMENT_QA_FAILED: '공고문 근거 답변을 안전하게 만들지 못했습니다. 원문을 직접 확인하거나 다시 시도해 주세요.',
  };
  return messages[error.code] ?? error.message;
}

function localHelpResponse(contextRevision: number, reply?: ReplyContext): CopilotChatResponse {
  const conclusion = '지금 보고 있는 공고에서 참가자격 결과, 확인할 사항, 선택한 요건의 원문 근거를 확인할 수 있어요.';
  return {
    answer: conclusion,
    intent: 'UNKNOWN',
    product_state: null,
    citations: [], sources: [], actions: [], warnings: [],
    external_processing_used: false, external_processing_scope: null,
    presentation: {
      conclusion,
      reasons: [
        { text: '예: “우리 회사가 참가할 수 있는지 알려줘”, “무엇을 확인해야 해?”, “첫 번째 조건 근거 보여줘”', requirement_key: null, evidence_refs: [] },
        { text: '비교 가능한 이전 버전이 있는 공고라면 변경된 자격요건도 확인할 수 있어요.', requirement_key: null, evidence_refs: [] },
        { text: 'AI 상세 설명을 켜면 질문 이해와 자연스러운 설명을 위해 현재 판정 결과·요건 상태와 판정에 필요한 회사 프로필 정보를 AI 처리에 사용해요.', requirement_key: null, evidence_refs: [] },
        { text: '공고문 근거 답변을 켜면 질문과 현재 공개 공고문을 외부 AI·임베딩 처리에 사용하고, 실제 인용 근거가 있는 경우에만 생성형 설명을 보여줘요.', requirement_key: null, evidence_refs: [] },
        { text: '답변 반영이나 재검증은 대화만으로 실행하지 않고, 제안을 확인한 뒤 명시적인 실행 버튼을 눌러야 합니다.', requirement_key: null, evidence_refs: [] },
      ],
      limitations: [], next_action: null,
    },
    reply_context: {
      request_id: null,
      context_revision: contextRevision,
      status: 'RESOLVED',
      requirement_key: null,
      visible_requirement_keys: reply?.visible_requirement_keys ?? [],
      last_read_receipt: reply?.last_read_receipt ?? null,
    },
  };
}

export function validateSources(response: CopilotChatResponse) {
  if (response.envelope) { validateEnvelope(response.envelope); return; }
  const refs = response.sources.map(s => s.ref);
  const used = [...new Set([...response.answer.matchAll(/\[(S\d+)\]/g)].map(m => m[1]))];
  const required = response.presentation?.reasons.flatMap(r => r.evidence_refs) ?? [];
  if (refs.some((ref, i) => ref !== 'S' + (i + 1)) ||
      [...used, ...required].some(ref => !refs.includes(ref)) || required.some(ref => !used.includes(ref)) ||
      response.citations.length !== used.length || response.citations.some((source, i) =>
        source.ref !== used[i] || canonical(source) !== canonical(response.sources.find(s => s.ref === source.ref)))) {
    throw new Error('응답의 근거 연결을 확인하지 못했습니다. 다시 조회해 주세요.');
  }
}

// Conversation normally lives in layout memory. A native navigation may hand a
// completed read state to the next product page, but never an in-flight request.
export class ConversationStore {
  private states = new Map<string, Conversation>();
  private listeners = new Set<() => void>();
  private failed = new Map<string, FailedRead>();
  constructor(private transport: Transport = sendConversationMessage) {}
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  get(caseId: string) {
    if (!this.states.has(caseId)) this.states.set(caseId, empty());
    return this.states.get(caseId)!;
  }
  private update(caseId: string, patch: Partial<Conversation>) {
    this.states.set(caseId, { ...this.get(caseId), ...patch });
    this.listeners.forEach(fn => fn());
  }
  snapshot(caseId: string): Conversation | null {
    const state = this.get(caseId);
    return state.busy ? null : structuredClone(state);
  }
  restore(caseId: string, state: Conversation) {
    if (!caseId || state.busy || !Array.isArray(state.turns)) return;
    this.states.set(caseId, { ...structuredClone(state), busy: false });
    this.failed.delete(caseId);
    this.listeners.forEach(fn => fn());
  }
  focus(caseId: string, key: string | null, reply?: ReplyContext | null) {
    this.update(caseId, { focus: key, reply: reply ?? this.get(caseId).reply, revision: this.get(caseId).revision + 1, busy: false });
  }
  selectTarget(caseId: string, targetId: string) {
    this.update(caseId, { targetId, focus: null });
  }
  newConversation(caseId: string) {
    const revision = this.get(caseId).revision + 1;
    this.failed.delete(caseId);
    this.update(caseId, { ...empty(), revision });
  }
  publish(caseId: string, response: CopilotChatResponse) {
    validateSources(response);
    const state = this.get(caseId), revision = state.revision + 1;
    this.update(caseId, { revision, busy: false, focus: null, reply: conversationReply(response.reply_context ?? undefined, state.reply),
      error: '', errorCode: '', turns: [...state.turns, { id: revision, question: '반영 후 현재 결과', response }] });
  }
  async retry(caseId: string, semanticProcessing?: boolean, documentProcessing?: boolean) {
    const failed = this.failed.get(caseId);
    if (!failed || this.get(caseId).busy) return;
    const { request, turnId } = failed;
    const old = this.get(caseId), revision = old.revision + 1;
    const turns = old.turns.map(turn => turn.id === turnId ? { ...turn, id: revision, response: undefined } : turn);
    this.update(caseId, { revision, busy: true, error: '', errorCode: '', turns });
    await this.perform(caseId, { ...request,
      semantic_processing: semanticProcessing ?? request.semantic_processing,
      document_processing: documentProcessing ?? request.document_processing,
      conversation_context: request.conversation_context ? {
        ...request.conversation_context, context_revision: revision, request_id: crypto.randomUUID(),
      } : undefined }, revision);
  }
  async ask(
    caseId: string,
    question: string,
    intent?: CopilotIntent,
    page?: 'QUALIFICATION' | 'ASK_BACK' | 'EVIDENCE' | 'CHANGES',
    semanticProcessing = false,
    documentProcessing = false,
    guided?: GuidedSelection,
  ) {
    const old = this.get(caseId);
    if (!caseId || old.busy || !question.trim()) return;
    const revision = old.revision + 1;
    this.update(caseId, { revision, busy: true, error: '', errorCode: '', turns: [...old.turns, { id: revision, question }] });

    if (!intent && isCopilotHelpQuestion(question)) {
      const response = localHelpResponse(revision, old.reply);
      this.failed.delete(caseId);
      this.update(caseId, { revision, busy: false, error: '', errorCode: '', reply: response.reply_context ?? undefined,
        focus: null, turns: this.get(caseId).turns.map(t => t.id === revision ? { ...t, response } : t) });
      return;
    }

    const request: ConversationRequest = {
        case_id: caseId, message: question, intent: intent ?? inferE1Intent(question),
        job_id: guided?.jobId, question_id: guided?.questionId,
        conversation_id: old.conversationId, context_revision: old.serverRevision, target_id: old.targetId,
        requirement_key: hasOrdinalReference(question) ? undefined : old.focus,
        semantic_processing: semanticProcessing || undefined,
        document_processing: documentProcessing || undefined,
        conversation_context: { request_id: crypto.randomUUID(), context_revision: revision, source_page: page,
          visible_requirement_keys: old.reply?.visible_requirement_keys ?? [], last_read_receipt: old.reply?.last_read_receipt,
          last_response_intent: old.turns.at(-1)?.response?.intent },
      };
    await this.perform(caseId, request, revision);
  }
  private async perform(caseId: string, request: ConversationRequest, revision: number) {
    try {
      const response = await this.transport(request);
      validateSources(response);
      if (response.envelope) validateEnvelope(response.envelope, caseId);
      if (this.get(caseId).revision !== revision) return;
      this.failed.delete(caseId);
      const current = this.get(caseId);
      this.update(caseId, { busy: false, reply: conversationReply(response.reply_context ?? undefined, current.reply),
        conversationId: response.envelope?.conversation_id ?? current.conversationId,
        serverRevision: response.envelope?.context_revision ?? current.serverRevision, targetId: undefined,
        focus: response.reply_context?.requirement_key ?? null,
        turns: current.turns.map(t => t.id === revision ? { ...t, response } : t) });
    } catch (error) {
      if (this.get(caseId).revision !== revision) return;
      this.failed.set(caseId, { request: structuredClone(request), turnId: revision });
      this.update(caseId, { busy: false, error: copilotReadErrorMessage(error),
        errorCode: error && typeof error === 'object' && 'code' in error ? String(error.code) : '' });
    }
  }
}
