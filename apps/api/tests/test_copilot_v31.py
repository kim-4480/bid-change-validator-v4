"""No live database/model. Contract failures, scope, recovery and frozen replay."""
from copy import deepcopy
import json
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.api.app.copilot.answer_validation import compose, mechanical, verify
from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.conversation_state import ConversationRepository
from apps.api.app.copilot.model_gateway import BudgetExceeded, ModelGateway
from apps.api.app.copilot.orchestration import coordinate, fallback_plan, resolve_target
from apps.api.app.copilot.tool_adapters import ProductTools, _document_excerpt
from apps.api.app.copilot.v31_contracts import (
    Claim, ConversationState, Draft, DraftClaim, EvidenceBundle, Fact, Scope, Source, Target, Task, TaskPlan, Verdicts,
)
from apps.api.app.errors import ApiError
from bidengine.rag.readiness import digest

FIXTURE_PATH = Path(__file__).parents[1] / 'eval/copilot_v31_replay.json'
REPLAY = json.loads(FIXTURE_PATH.read_text(encoding='utf-8'))


def scope():
    return Scope(**{k: REPLAY[k] for k in ('case_id', 'company_id', 'notice_id', 'notice_version_id', 'analysis_run_id', 'judgment_run_id')})


def bundle():
    context = scope()
    return EvidenceBundle(scope=context,
        facts=[Fact(fact_id=f['id'], kind=f['kind'], text=f['text'], source_ids=['s-' + f['id']], target_kind=f['target'], scope=context) for f in REPLAY['facts']],
        sources=[Source(source_id='s-' + f['id'], kind='PRODUCT' if f['kind'] == 'SERVER_RESULT' else 'DOCUMENT', quote=f['text'], scope=context) for f in REPLAY['facts']])


class FakeGateway:
    def __init__(self, replies=None):
        self.replies = replies or {}
        self.started = monotonic()
        self.model = 'scripted-fake'
        self.calls = []
        self.bodies = []
    def remaining(self): return 40
    def call(self, stage, system, body, schema):
        self.calls.append({'stage': stage, 'model': self.model, 'usage': None})
        self.bodies.append(body)
        response = self.replies.get(stage)
        if isinstance(response, Exception) or response is None:
            raise response or RuntimeError('fake unavailable')
        if callable(response): response = response(body)
        if schema is Verdicts and isinstance(response, dict):
            response = {'task_coverage': 'COMPLETE', **response}
        return schema.model_validate(response)


def draft(text='병원 급식 실적은 제외됩니다.', fid='exception'):
    return Draft(claims=[DraftClaim(claim_id='c1', text=text, fact_ids=[fid], source_ids=['s-' + fid])])


@pytest.mark.parametrize('text', [
    '참가 가능합니다.', '이제 모두 준비됐습니다.', '병원 급식 실적도 포함합니다.',
    '800식이 아니라 80식이면 됩니다.', '2년 이내 2곳 또는 1년 운영이면 됩니다.',
])
def test_contradicted_prose_never_published(text):
    b = bundle()
    gateway = FakeGateway({'generate': draft(text), 'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'CONTRADICTED', 'reason': 'injected known contradiction'}]},
                           'repair': draft(text), 'revalidate': {'verdicts': [{'claim_id': 'c1', 'status': 'CONTRADICTED', 'reason': 'still wrong'}]}})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    claims, partial, _ = compose(b, TaskPlan(goal='설명', tasks=[Task(kind='READ_DOCUMENT', question='설명')]), state, gateway)
    assert text not in [c.text for c in claims]
    assert partial and len(gateway.calls) == 4
    assert claims == []


def test_supported_paraphrase_is_preserved_and_does_not_repair():
    text = '요건은 공고일 기준 최근 2년, 2곳 이상, 하루 평균 800식 이상, 1년 이상 운영이며 병원은 제외됩니다.'
    gateway = FakeGateway({'generate': draft(text), 'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'same meaning fixture'}]}})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    claims, partial, _ = compose(bundle(), TaskPlan(goal='실적', tasks=[Task(kind='READ_DOCUMENT', question='실적')]), state, gateway)
    assert not partial and claims[0].text == text and len(gateway.calls) == 2


def test_verifier_failure_does_not_promote_raw_document_to_answer_prose():
    gateway = FakeGateway({'generate': draft('검증하지 않은 문장'), 'validate': TimeoutError()})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    claims, partial, _ = compose(bundle(), TaskPlan(goal='실적', tasks=[Task(kind='READ_DOCUMENT', question='실적')]), state, gateway)
    assert partial and claims == []
    assert '검증하지 않은 문장' not in [c.text for c in claims]


def test_code_difference_question_routes_to_changes_without_document_dump():
    request = CopilotChatRequest(case_id=scope().case_id, message='1224와 1227은 무슨 차이야?')
    plan = fallback_plan(request)
    assert [task.kind for task in plan.tasks] == ['READ_CHANGES']

    context = scope()
    rows = [
        ('impact', '현재 판정과 연결된 재검증 기록이 없어 전후 영향을 단정할 수 없습니다.'),
        ('before', '이전 버전 1: 폐기물수집·운반업(1224) 등록업체 (MODIFIED)'),
        ('after', '현재 버전 2: 폐기물수집·운반업(1227) 등록업체 (MODIFIED)'),
        ('unchanged', '현재 버전 2: 폐기물중간처분업(1257) 등록업체 (UNCHANGED)'),
    ]
    evidence = EvidenceBundle(
        scope=context,
        facts=[Fact(fact_id=key, kind='SERVER_RESULT', text=text, source_ids=['s-' + key], target_kind='CHANGE', scope=context) for key, text in rows],
        sources=[Source(source_id='s-' + key, kind='PRODUCT', quote=text, scope=context) for key, text in rows],
    )
    claims, partial, _ = compose(evidence, plan, ConversationState(conversation_id=uuid4(), owner='u', scope=context), FakeGateway())
    assert partial
    assert [claim.text for claim in claims] == [rows[1][1], rows[2][1], rows[0][1]]
    assert all(claim.method == 'rule' for claim in claims)
    assert all('1257' not in claim.text for claim in claims)


def test_document_excerpt_removes_mojibake_duplicates_and_focuses_on_question():
    noise = '捤獥汤捯湰灧湰灧桤灧湯湷湯湷湯湷氠瑢'
    repeated = '입찰자는 공고문을 확인해야 합니다.'
    filler = '\n'.join(f'일반 안내 문장 {index}' for index in range(200))
    relevant = '폐기물수집·운반업 코드는 이전 1224에서 현재 1227로 변경되었습니다.'
    text = f'{noise}\n氠瑢\n{repeated}\n{filler}\n{relevant}\n{repeated}'
    excerpt = _document_excerpt(text, '1224와 1227은 무슨 차이야?')
    assert relevant in excerpt
    assert noise not in excerpt and '氠瑢' not in excerpt
    assert excerpt.count(repeated) <= 1
    assert len(excerpt) <= 1600


def test_invalid_sources_and_cross_company_rejected():
    b = bundle()
    c = Claim(**draft().claims[0].model_dump())
    c.source_ids = ['s-judgment']
    assert mechanical(c, b) == 'UNRELATED_SOURCE'
    c.source_ids = ['missing']
    assert mechanical(c, b) == 'INVALID_REFERENCE'
    c.source_ids = ['s-exception']
    b.facts[1].scope = b.facts[1].scope.model_copy(update={'company_id': uuid4()})
    assert mechanical(c, b) == 'CROSS_SCOPE'


def test_verifier_normalizes_model_source_pointer_from_server_fact_edges():
    raw = draft().claims[0].model_copy(update={'source_ids': ['s-judgment']})
    gateway = FakeGateway({'validate': {
        'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'fixture'}],
    }})

    claims, _ = verify(Draft(claims=[raw]), bundle(), gateway)

    assert claims[0].validation == 'SUPPORTED'
    assert claims[0].source_ids == ['s-exception']


def test_manual_claim_has_no_requirement_but_keeps_source():
    c = Claim(**draft(REPLAY['facts'][2]['text'], 'manual').claims[0].model_dump())
    assert mechanical(c, bundle()) is None
    assert bundle().facts[2].requirement_key is None


def test_server_owner_revision_and_late_commit():
    repo = ConversationRepository()
    state = repo.load('owner', scope())
    with pytest.raises(ApiError, match='접근'):
        repo.load('other', scope(), state.conversation_id, 0)
    second = state.model_copy(deep=True)
    repo.commit(state, 0)
    with pytest.raises(ApiError, match='늦게'):
        repo.commit(second, 0)
    with pytest.raises(ApiError):
        repo.load('owner', scope().model_copy(update={'case_id': uuid4()}), state.conversation_id, 1)


def test_mixed_ordinals_clarify_and_explicit_manual_resolves():
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    for kind in ('REQUIREMENT', 'MANUAL'):
        state.targets.append(Target(target_id=kind, kind=kind, label=kind, message_id='m1', ordinal=1, fact_ids=['manual'], source_ids=['s-manual']))
    request = CopilotChatRequest(case_id=scope().case_id, message='첫 번째 원문')
    assert resolve_target(request, state)[1]
    request.message = '첫 번째 직접 확인 항목 원문'
    target, clarification = resolve_target(request, state)
    assert target.kind == 'MANUAL' and clarification is None


def test_askability_adapter_and_manual_citation(monkeypatch):
    from apps.api.tests.test_copilot_required_checks_narration import _fixture
    summary, checks, profile, _ = _fixture(with_question=True)
    checks.questions[0].askable = False
    monkeypatch.setattr('apps.api.app.copilot.product_tools.get_qualification_summary', lambda *a: summary)
    monkeypatch.setattr('apps.api.app.copilot.product_tools.get_required_checks', lambda *a: checks)
    p = summary.provenance
    case = SimpleNamespace(id=p.case_id, company_id=p.company_id, notice_id=p.notice_id, current_version_id=p.notice_version_id)
    tools = ProductTools(SimpleNamespace(), case)
    tools.required_checks()
    assert tools.bundle.capabilities == {'answerable_count': 0, 'unanswerable_count': 1, 'manual_review_count': 1}
    manual = [f for f in tools.bundle.facts if f.target_kind == 'MANUAL']
    assert manual and manual[0].source_ids
    assert any(s.quote.startswith('국가계약법') for s in tools.bundle.sources)


class ReplayTools:
    def __init__(self):
        self.scope = scope()
        self.bundle = EvidenceBundle(scope=self.scope, fingerprints={'product': digest(REPLAY)})
        self.bundle.server_context = {'overall_status': 'ineligible', 'basis': REPLAY['facts'][0]['text']}
        self.card = None
        self.summary = None
        self.trace = []
    def _summary(self): return None
    def assert_fresh(self): pass
    def execute(self, task):
        mapping = {'READ_JUDGMENT': ['judgment'], 'READ_PROFILE': [], 'READ_DOCUMENT': ['exception'], 'READ_CHECKS': ['manual']}
        if task.kind not in mapping:
            self.bundle.coverage[task.kind] = 'UNAVAILABLE'
            self.bundle.limitations.append('합성 fixture에는 이 조회의 데이터가 없습니다: ' + task.kind)
            return
        data = bundle()
        for fid in mapping[task.kind]:
            if fid in {f.fact_id for f in self.bundle.facts}:
                continue
            self.bundle.facts.append(next(f for f in data.facts if f.fact_id == fid))
            self.bundle.sources.append(next(s for s in data.sources if s.source_id == 's-' + fid))
        self.bundle.coverage[task.kind] = 'FOUND'


def replay():
    repository = ConversationRepository()
    result = None
    outputs = []
    for turn in REPLAY['turns']:
        request = CopilotChatRequest(case_id=scope().case_id, message=turn['question'], response_version='3.1',
                                     conversation_id=result.conversation_id if result else None,
                                     context_revision=result.context_revision if result else None)
        generated = Draft(claims=[DraftClaim(claim_id=fid, text=next(f['text'] for f in REPLAY['facts'] if f['id'] == fid),
                                            fact_ids=[fid], source_ids=['s-' + fid]) for fid in turn['facts']])
        gateway = FakeGateway({'plan': TaskPlan(goal=turn['question'], tasks=[Task(kind=k, question=turn['question']) for k in turn['tasks']]),
                               'generate': generated, 'validate': {'verdicts': [{'claim_id': fid, 'status': 'SUPPORTED', 'reason': 'frozen exact source'} for fid in turn['facts']]}})
        result, _ = coordinate(request, 'fixture-user', ReplayTools(), repository=repository, gateway=gateway)
        assert result.processing.task_status == 'PASS'
        assert {fid for c in result.claims for fid in c.fact_ids} == set(turn['facts'])
        assert all(c.source_ids for c in result.claims)
        outputs.append(result.model_dump(mode='json'))
    return outputs


def test_frozen_four_turn_compound_flow():
    outputs = replay()
    assert [o['context_revision'] for o in outputs] == [1, 2, 3, 4]
    assert len(outputs[0]['processing']['tools']) == 4
    assert outputs[2]['follow_up_targets'][0]['kind'] == 'DOCUMENT'


def test_gateway_deadline_input_and_attempt_caps():
    gateway = ModelGateway(client=SimpleNamespace())
    gateway.deadline = monotonic() - 1
    with pytest.raises(BudgetExceeded): gateway.call('generate', '', {}, Draft)
    gateway.deadline = monotonic() + 45
    with pytest.raises(BudgetExceeded): gateway.call('generate', 'x' * 17000, {}, Draft)
    gateway.calls = [{'stage': 'generate'}] * 4
    with pytest.raises(BudgetExceeded): gateway.call('validate', '', {}, Verdicts)


def test_api_v31_dispatch_preserves_legacy_contract(monkeypatch):
    from apps.api.app.copilot.router import copilot_chat
    seen = {}
    case = SimpleNamespace()
    monkeypatch.setattr('apps.api.app.copilot.router.authorize_case_access', lambda *a: case)
    def handler(db, req, user, actual_case, semantic):
        seen.update(case=actual_case, semantic=semantic, version=req.response_version)
        return 'v31'
    monkeypatch.setattr('apps.api.app.copilot.orchestration.chat_v31', handler)
    request = CopilotChatRequest(case_id=scope().case_id, message='질문', response_version='3.1')
    assert copilot_chat(request, db=object(), user=object(), semantic_processing=True) == 'v31'
    assert seen == {'case': case, 'semantic': True, 'version': '3.1'}


def test_anonymous_v31_rejected_before_state_creation():
    from apps.api.app.copilot.orchestration import chat_v31
    with pytest.raises(ApiError) as error:
        chat_v31(None, None, None, None, True)
    assert error.value.status_code == 401


def test_supported_claim_survives_failed_sibling_repair():
    good = draft().claims[0].model_copy(update={'claim_id': 'good'})
    bad = draft('병원도 포함합니다.').claims[0].model_copy(update={'claim_id': 'bad'})
    gateway = FakeGateway({'generate': Draft(claims=[good, bad]), 'validate': {'verdicts': [
        {'claim_id': 'good', 'status': 'SUPPORTED', 'reason': 'fixture'},
        {'claim_id': 'bad', 'status': 'CONTRADICTED', 'reason': 'fixture'}]}, 'repair': RuntimeError('failed')})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    claims, partial, _ = compose(bundle(), TaskPlan(goal='실적', tasks=[Task(kind='READ_DOCUMENT', question='실적')]), state, gateway)
    assert partial and any(c.claim_id == 'good' and c.text == good.text for c in claims)
    assert not any(c.claim_id == 'bad' for c in claims)


def test_repair_ignores_echoed_supported_sibling_and_accepts_only_failed_claim():
    good = draft().claims[0].model_copy(update={'claim_id': 'good'})
    bad = draft('병원도 포함합니다.').claims[0].model_copy(update={'claim_id': 'bad'})
    fixed = draft('병원 급식 실적은 제외됩니다.').claims[0].model_copy(update={'claim_id': 'bad'})
    gateway = FakeGateway({
        'generate': Draft(claims=[good, bad]),
        'validate': {'verdicts': [
            {'claim_id': 'good', 'status': 'SUPPORTED', 'reason': 'fixture'},
            {'claim_id': 'bad', 'status': 'CONTRADICTED', 'reason': 'fixture'},
        ]},
        'repair': Draft(claims=[good.model_copy(update={'text': '검증된 문장을 바꾸려는 응답'}), fixed]),
        'revalidate': {'verdicts': [
            {'claim_id': 'bad', 'status': 'SUPPORTED', 'reason': 'fixed'},
        ]},
    })
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())

    claims, partial, _ = compose(
        bundle(), TaskPlan(goal='실적', tasks=[Task(kind='READ_DOCUMENT', question='실적')]), state, gateway
    )

    assert not partial
    assert {claim.claim_id: claim.text for claim in claims} == {
        'good': good.text,
        'bad': fixed.text,
    }


def test_assumptions_never_call_write_or_become_server_result():
    tools = ReplayTools()
    tools.db = SimpleNamespace(commit=lambda: pytest.fail('chat attempted a write'))
    question = '실적 1건을 추가하면?'
    gateway = FakeGateway({'plan': TaskPlan(goal=question, tasks=[Task(kind='REVIEW_ASSUMPTION', question=question)])})
    result, adapter = coordinate(CopilotChatRequest(case_id=scope().case_id, message=question), 'u', tools,
                                 repository=ConversationRepository(), gateway=gateway)
    assert not result.actions
    assert any(f.kind == 'ASSUMPTION' for f in adapter.bundle.facts)
    assert not any(f.kind == 'SERVER_RESULT' for f in adapter.bundle.facts)
    assert result.processing.task_status != 'PASS'


def test_changed_context_invalidates_old_target():
    repo = ConversationRepository()
    state = repo.load('u', scope())
    state.targets = [Target(target_id='old', kind='DOCUMENT', label='old', message_id='m', ordinal=1,
                            fact_ids=['exception'], source_ids=['s-exception'])]
    repo.commit(state, 0)
    tools = ReplayTools()
    tools.scope = scope().model_copy(update={'analysis_run_id': uuid4()})
    tools.bundle.scope = tools.scope
    result, _ = coordinate(CopilotChatRequest(case_id=scope().case_id, message='그 조건', target_id='old',
                                            conversation_id=state.conversation_id, context_revision=1), 'u', tools,
                           repository=repo, gateway=FakeGateway())
    assert result.clarification and not result.claims and not result.follow_up_targets


def test_real_sdk_transport_enforces_one_attempt_usage_and_late_discard():
    import httpx
    from openai import OpenAI
    received = []
    def handler(request):
        received.append(json.loads(request.content))
        return httpx.Response(200, json={'id': 'test', 'object': 'chat.completion', 'created': 0, 'model': 'fixture',
            'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': draft().model_dump_json()}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}})
    client = OpenAI(api_key='synthetic-test-key', http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    gateway = ModelGateway(client=client)
    result = gateway.call('generate', 'fixture', {}, Draft)
    assert result.claims and received[0]['max_completion_tokens'] == 3000
    assert gateway.calls[0]['usage']['total_tokens'] == 30
    def fail(request):
        received.append('failure')
        return httpx.Response(500, json={'error': {'message': 'fixture'}})
    gateway.client = OpenAI(api_key='synthetic-test-key', http_client=httpx.Client(transport=httpx.MockTransport(fail)))
    with pytest.raises(Exception): gateway.call('validate', 'fixture', {}, Verdicts)
    assert received.count('failure') == 1
    def late(request):
        gateway.deadline = monotonic() - 1
        return handler(request)
    gateway.client = OpenAI(api_key='synthetic-test-key', http_client=httpx.Client(transport=httpx.MockTransport(late)))
    with pytest.raises(BudgetExceeded, match='LATE_MODEL_RESULT'):
        gateway.call('repair', 'fixture', {}, Draft)


def test_cross_version_source_rejected_even_when_fact_is_current():
    b = bundle()
    b.sources[1].scope = scope().model_copy(update={'notice_version_id': uuid4()})
    assert mechanical(Claim(**draft().claims[0].model_dump()), b) == 'SOURCE_SCOPE_MISMATCH'


def test_missing_required_fact_is_partial_even_if_other_claim_passes():
    question = REPLAY['turns'][0]['question']
    gateway = FakeGateway({'plan': TaskPlan(goal=question, tasks=[Task(kind='READ_JUDGMENT', question=question), Task(kind='READ_DOCUMENT', question=question)]),
                           'generate': draft(), 'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'fixture'}]}})
    result, _ = coordinate(CopilotChatRequest(case_id=scope().case_id, message=question), 'u', ReplayTools(),
                           repository=ConversationRepository(), gateway=gateway)
    assert result.processing.task_status == 'PARTIAL'
    assert any(e.get('uncovered_fact_ids') == ['judgment'] for e in result.processing.validation_events)


def test_long_extractive_source_is_preserved_without_schema_crash():
    b = bundle()
    b.sources[1].quote = '원문 조건과 예외. ' * 500
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    claims, partial, _ = compose(b, TaskPlan(goal='원문', tasks=[Task(kind='READ_DOCUMENT', question='원문')]), state, FakeGateway())
    assert partial
    assert claims == []
    assert len(b.sources[1].quote) > 2500


def test_actual_asgi_v31_four_turn_route_and_serialization(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from apps.api.app.copilot import orchestration, router
    from apps.api.app.database import get_db
    from apps.api.app.auth import get_optional_current_user
    api = FastAPI()
    api.include_router(router.router)
    api.dependency_overrides[get_db] = lambda: SimpleNamespace()
    api.dependency_overrides[get_optional_current_user] = lambda: SimpleNamespace(id='fixture-user')
    monkeypatch.setattr(router, 'authorize_case_access', lambda *a: object())
    monkeypatch.setattr(orchestration, 'ProductTools', lambda *a, **kw: ReplayTools())
    index = [0]
    def gateway_factory():
        turn = REPLAY['turns'][index[0]]
        index[0] += 1
        return FakeGateway({'plan': TaskPlan(goal=turn['question'], tasks=[Task(kind=k, question=turn['question']) for k in turn['tasks']]),
            'generate': Draft(claims=[DraftClaim(claim_id=fid, text=next(f['text'] for f in REPLAY['facts'] if f['id'] == fid),
                                                fact_ids=[fid], source_ids=['s-' + fid]) for fid in turn['facts']]),
            'validate': {'verdicts': [{'claim_id': fid, 'status': 'SUPPORTED', 'reason': 'frozen'} for fid in turn['facts']]}})
    monkeypatch.setattr(orchestration, 'ModelGateway', gateway_factory)
    with TestClient(api) as client:
        envelope = None
        for turn in REPLAY['turns']:
            response = client.post('/api/v1/copilot/chat', headers={'X-Copilot-Semantic-Processing': 'true'}, json={
                'case_id': str(scope().case_id), 'message': turn['question'], 'response_version': '3.1',
                'conversation_id': envelope['conversation_id'] if envelope else None,
                'context_revision': envelope['context_revision'] if envelope else None})
            assert response.status_code == 200, response.text
            envelope = response.json()['envelope']
            assert envelope['processing']['task_status'] == 'PASS'
        assert envelope['context_revision'] == 4


def test_supported_fact_reference_does_not_prove_all_exceptions_covered():
    gateway = FakeGateway({'generate': draft('최근 2년 실적이 필요합니다.'),
        'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'true but incomplete'}],
                     'task_coverage': 'PARTIAL', 'missing_topics': ['기관 제외', '식수', '운영기간']}})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    claims, partial, events = compose(bundle(), TaskPlan(goal='실적의 전체 조건', tasks=[Task(kind='READ_DOCUMENT', question='전체')]), state, gateway)
    assert partial and claims[0].text == '최근 2년 실적이 필요합니다.'
    assert any(e.get('missing_topics') == ['기관 제외', '식수', '운영기간'] for e in events)


def test_guided_partial_keeps_verified_claims_without_dumping_uncovered_sources():
    b = bundle()
    b.server_context['guided_question'] = {
        'answer_scope': '질문에 직접 필요한 내용',
        'completion_criteria': ['핵심 조건을 설명'],
        'excluded': ['원문 전체 나열'],
    }
    gateway = FakeGateway({'generate': draft('최근 2년 실적이 필요합니다.'),
        'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'true but incomplete'}],
                     'task_coverage': 'PARTIAL', 'missing_topics': ['기관 제외']}})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())

    claims, partial, events = compose(
        b, TaskPlan(goal='실적의 전체 조건', tasks=[Task(kind='READ_DOCUMENT', question='전체')]), state, gateway
    )

    assert partial
    assert [claim.text for claim in claims] == ['최근 2년 실적이 필요합니다.']
    assert all(claim.method == 'semantic' for claim in claims)
    assert any(event.get('missing_topics') == ['기관 제외'] for event in events)


def test_guided_complete_drops_failed_extra_when_supported_claims_cover_server_criteria():
    b = bundle()
    b.server_context['guided_question'] = {
        'answer_scope': '질문에 직접 필요한 내용',
        'completion_criteria': ['핵심 조건을 설명'],
        'excluded': ['원문 전체 나열'],
    }
    good = draft().claims[0]
    bad = DraftClaim(claim_id='bad', text='근거 없는 추가 문장', fact_ids=['missing'], source_ids=['missing'])
    gateway = FakeGateway({'generate': Draft(claims=[good, bad]),
        'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'criterion covered'}],
                     'task_coverage': 'COMPLETE', 'missing_topics': []}})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())

    claims, partial, _ = compose(
        b, TaskPlan(goal='실적의 전체 조건', tasks=[Task(kind='READ_DOCUMENT', question='전체')]), state, gateway
    )

    assert not partial
    assert [claim.claim_id for claim in claims] == ['c1']
    assert [call['stage'] for call in gateway.calls] == ['generate', 'validate']


def test_document_guided_question_uses_server_structural_coverage_when_verifier_overreaches():
    b = bundle()
    b.server_context['guided_question'] = {
        'question_id': 'documents_deadlines_methods',
        'answer_scope': '서류 기한 방법 제출처',
        'completion_criteria': ['서류별 단계·기한·방법·제출처를 연결한다.'],
        'excluded': ['실제 제출 완료 증명'],
    }
    text = (
        '[필수] 현장 확인서를 준비하고 입찰서는 나라장터에 제출합니다. '
        '[확인 필요] 산출내역서 제출처는 확인해야 합니다. '
        '[조건부] 낙찰 시 청렴계약 서약서를 제출합니다.'
    )
    gateway = FakeGateway({'generate': draft(text),
        'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'facts support prose'}],
                     'task_coverage': 'PARTIAL', 'missing_topics': ['배치 방식']}})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())

    claims, partial, events = compose(
        b, TaskPlan(goal='서류', tasks=[Task(kind='READ_DOCUMENT', question='서류')]), state, gateway
    )

    assert not partial and claims
    assert any(event.get('stage') == 'server_guided_coverage' for event in events)


def test_next_checks_uses_server_boundary_and_action_coverage():
    b = bundle()
    boundary_source = Source(
        source_id='guided-boundary-source', kind='PRODUCT', quote='앱과 외부 확인 범위를 구분한다.', scope=scope()
    )
    b.sources.append(boundary_source)
    b.facts.append(Fact(
        fact_id='guided-next-checks-product-boundary', kind='SERVER_RESULT',
        text=boundary_source.quote, source_ids=[boundary_source.source_id], scope=scope()
    ))
    b.server_context['guided_question'] = {
        'question_id': 'next_checks',
        'completion_criteria': ['이유와 행동', '앱과 외부 구분'],
        'excluded': ['실제 완료 추정'],
    }
    claims = [
        DraftClaim(claim_id='boundary', text='앱과 외부 확인 범위를 구분합니다.',
                   fact_ids=['guided-next-checks-product-boundary'], source_ids=['guided-boundary-source']),
        DraftClaim(claim_id='one', text='등록 상태를 확인하고 증빙과 대조해야 합니다.', fact_ids=['exception'], source_ids=['s-exception']),
        DraftClaim(claim_id='two', text='허가 여부를 확인해야 하며 원문과 대조해야 합니다.', fact_ids=['exception'], source_ids=['s-exception']),
        DraftClaim(claim_id='three', text='제출 여부를 확인하고 담당 기록과 대조해야 합니다.', fact_ids=['exception'], source_ids=['s-exception']),
    ]
    gateway = FakeGateway({'generate': Draft(claims=claims), 'validate': {
        'verdicts': [{'claim_id': claim.claim_id, 'status': 'SUPPORTED', 'reason': 'fixture'} for claim in claims],
        'task_coverage': 'PARTIAL', 'missing_topics': ['배치 방식'],
    }})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())

    result, partial, events = compose(
        b, TaskPlan(goal='확인', tasks=[Task(kind='READ_CHECKS', question='확인')]), state, gateway
    )

    assert not partial and len(result) == 4
    assert any(event.get('reason') == 'SERVER_BOUNDARY_AND_CHECK_ACTIONS_PRESENT' for event in events)


def test_preparation_order_uses_server_sequence_coverage():
    b = bundle()
    b.server_context['guided_question'] = {
        'question_id': 'preparation_order',
        'completion_criteria': ['제안 순서와 원문상 강제 순서를 구분한다.'],
        'excluded': ['완료 추정'],
    }
    text = (
        '권장 순서는 자격 확인부터 계약까지입니다. 입찰서 제출 전 현장을 방문하고 '
        '업종 등록은 마감일 전일까지 마칩니다. 낙찰 시 계약하며, 지난 기한은 완료를 추정하지 않습니다.'
    )
    gateway = FakeGateway({'generate': draft(text), 'validate': {
        'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'fixture'}],
        'task_coverage': 'PARTIAL', 'missing_topics': ['표현 배치'],
    }})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())

    claims, partial, events = compose(
        b, TaskPlan(goal='순서', tasks=[Task(kind='READ_DOCUMENT', question='순서')]), state, gateway
    )

    assert not partial and claims
    assert any(event.get('reason') == 'SERVER_RECOMMENDED_AND_MANDATORY_SEQUENCE_PRESENT' for event in events)


def test_empty_reference_sibling_does_not_drop_supported_prose():
    good = draft().claims[0]
    bad = DraftClaim(claim_id='empty', text='회사 실적이 충분합니다.', fact_ids=[], source_ids=[])
    gateway = FakeGateway({'generate': Draft(claims=[good, bad]),
        'validate': {'verdicts': [{'claim_id': 'c1', 'status': 'SUPPORTED', 'reason': 'fixture'}]}})
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    claims, partial, _ = compose(bundle(), TaskPlan(goal='실적', tasks=[Task(kind='READ_DOCUMENT', question='실적')]), state, gateway)
    assert partial and any(c.text == good.text and c.method == 'semantic' for c in claims)
    assert not any(c.text == bad.text for c in claims)


@pytest.mark.parametrize('message', ['101번째 원문', '0번째 원문', '-1번째 원문', '2.5번째 원문', '첫 번째와 두 번째 원문'])
def test_invalid_ordinal_never_rebinds_to_valid_suffix(message):
    state = ConversationState(conversation_id=uuid4(), owner='u', scope=scope())
    state.targets = [Target(target_id='one', kind='DOCUMENT', label='first', message_id='m', ordinal=1,
                            fact_ids=['exception'], source_ids=['s-exception'])]
    target, clarification = resolve_target(CopilotChatRequest(case_id=scope().case_id, message=message), state)
    assert target is None and clarification


def test_stale_target_cannot_create_a_proposal(monkeypatch):
    repo = ConversationRepository()
    state = repo.load('u', scope())
    state.targets = [Target(target_id='old', kind='REQUIREMENT', label='old', message_id='m', ordinal=1,
                            fact_ids=['manual'], source_ids=['s-manual'], requirement_key='R1')]
    state.fingerprints = {'product': 'old-fingerprint'}
    repo.commit(state, 0)
    monkeypatch.setattr('apps.api.app.copilot.chat.chat', lambda *a: pytest.fail('stale target reached proposal'))
    request = CopilotChatRequest(case_id=scope().case_id, message='그 항목 반영해줘', target_id='old',
                                conversation_id=state.conversation_id, context_revision=1,
                                user_input={'satisfies_requirement': True})
    result, _ = coordinate(request, 'u', ReplayTools(), repository=repo, gateway=FakeGateway())
    assert result.clarification and not result.actions


def test_change_adapter_keeps_version_scopes_and_detects_baseline_change(monkeypatch):
    from apps.api.app.copilot.actions import ChangedNoticeResult
    from apps.api.app.copilot.contracts import RevalidationProvenance, VersionState
    from bidengine.diff.requirement_diff import RequirementChange
    from bidengine.contracts import QualificationRequirement
    s = scope()
    p = RevalidationProvenance(case_id=s.case_id, notice_id=s.notice_id, company_id=s.company_id, rule_version='fixture',
        baseline=VersionState(notice_version_id=uuid4(), version_number=1, analysis_run_id=uuid4(), judgment_run_id=uuid4(), analysis_status='SUCCEEDED'),
        current=VersionState(notice_version_id=s.notice_version_id, version_number=2, analysis_run_id=s.analysis_run_id, judgment_run_id=s.judgment_run_id, analysis_status='SUCCEEDED'))
    old = QualificationRequirement(requirement_key='R1', notice_version_id=str(p.baseline.notice_version_id), type='REGION', raw='이전 지역 요건')
    new = old.model_copy(update={'notice_version_id': str(s.notice_version_id), 'raw': '현재 지역 요건'})
    result = ChangedNoticeResult(provenance=p, changes=[RequirementChange(identity='key:R1', baseline_key='R1', current_key='R1', change_type='MODIFIED', baseline=old, current=new)])
    monkeypatch.setattr('apps.api.app.copilot.tool_adapters.get_changed_notice', lambda *a: result)
    case = SimpleNamespace(id=s.case_id, company_id=s.company_id, notice_id=s.notice_id, current_version_id=s.notice_version_id)
    tools = ProductTools(SimpleNamespace(refresh=lambda _: None), case)
    tools.changes()
    assert {f.scope.notice_version_id for f in tools.bundle.facts} == {s.notice_version_id, p.baseline.notice_version_id}
    assert all(next(src for src in tools.bundle.sources if src.source_id == f.source_ids[0]).scope == f.scope for f in tools.bundle.facts)
    tools.assert_fresh()
    result.changes[0].baseline.raw = '새로 수정된 이전 버전 요건'
    with pytest.raises(ValueError, match='CHANGE_SCOPE_CHANGED'):
        tools.assert_fresh()
