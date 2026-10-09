"""Local Golden E2E and confirmation/privacy boundaries. No real model calls."""

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from apps.api.app.analysis_models import QualificationAnalysisRun
from apps.api.app.auth import get_optional_current_user
from apps.api.app.auth_models import AppUser
from apps.api.app.copilot import chat as flow
from apps.api.app.copilot import document_qa as grounded_flow
from apps.api.app.copilot import router as copilot_router
from apps.api.app.copilot.actions import confirm_action, get_changed_notice, propose_answer
from apps.api.app.copilot.contracts import ActionInput, ConfirmAction, RevalidationProposal
from apps.api.app.database import SessionLocal, get_db
from bidengine.rag.answer import GroundedCitation, GroundedDocumentAnswer
from bidengine.rag.store import VersionFaissIndex
from apps.api.app.judgment_models import QualificationJudgmentRun
from apps.api.app.main import app
from apps.api.app.models import Company, PreflightCase
from apps.api.app.qualification.judgment import QualificationJudgmentError, run_qualification_judgment
from apps.api.app.revalidation_models import QualificationRevalidationRun
from apps.api.tests.test_copilot_product_tools import state
from apps.api.tests.test_document_rag_store import FakeEmbeddings, _record
from apps.api.tests.test_mvp_golden_e2e import _cleanup, _seed_golden_case


pytestmark = pytest.mark.usefixtures("seed_required_master_codes")


@pytest.fixture
def api(state):
    db = state[0]
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def ask(api, case_id, message, **extra):
    response = api.post('/api/v1/copilot/chat', json={'case_id': str(case_id), 'message': message, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_company_user_cannot_access_other_company_copilot_case(state, api):
    db, case, _, _ = state
    foreign_user = AppUser(
        username="foreign-company-user",
        password_hash="unused-in-dependency-override",
        company_id=uuid4(),
        role="USER",
        active=True,
    )
    app.dependency_overrides[get_optional_current_user] = lambda: foreign_user
    try:
        chat_response = api.post(
            "/api/v1/copilot/chat",
            json={"case_id": str(case.id), "message": "현재 판정 요약"},
        )
        assert chat_response.status_code == 403
        assert chat_response.json()["error"]["code"] == "COMPANY_ACCESS_DENIED"

        proposal = propose_answer(
            db,
            case.id,
            "REQ-REGISTRATION",
            ActionInput(satisfies_requirement=True),
        ).model_dump(mode="json")
        confirm_response = api.post(
            "/api/v1/copilot/actions/confirm",
            json={"confirmed": True, "action": proposal},
        )
        assert confirm_response.status_code == 403
        assert confirm_response.json()["error"]["code"] == "COMPANY_ACCESS_DENIED"
    finally:
        app.dependency_overrides.pop(get_optional_current_user, None)


def test_case_access_is_checked_before_semantic_processing(state, api, monkeypatch):
    _, case, _, _ = state
    foreign_user = AppUser(
        username="foreign-semantic-user",
        password_hash="unused-in-dependency-override",
        company_id=uuid4(),
        role="USER",
        active=True,
    )
    app.dependency_overrides[get_optional_current_user] = lambda: foreign_user
    monkeypatch.setattr(
        copilot_router,
        "SemanticRouter",
        lambda: pytest.fail("semantic processing ran before case authorization"),
    )
    try:
        response = api.post(
            "/api/v1/copilot/chat",
            headers={"X-Copilot-Semantic-Processing": "true"},
            json={"case_id": str(case.id), "message": "모호한 문서 질문"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "COMPANY_ACCESS_DENIED"
    finally:
        app.dependency_overrides.pop(get_optional_current_user, None)


def test_golden_summary_evidence_proposal_confirm_replay(state, api):
    db, case, _, source = state
    summary = ask(api, case.id, '우리 회사 참여 가능해?')
    assert summary['product_state']['overall_status'] == source.overall_status
    checks = ask(api, case.id, '무엇을 확인해야 해?')
    assert any(q['requirement_key'] == 'REQ-REGISTRATION' and q['askable'] for q in checks['product_state']['questions'])
    evidence = ask(api, case.id, '근거 원문 어디야?', requirement_key='REQ-REGISTRATION')
    assert [s['evidence']['evidence_key'] for s in evidence['sources']] == ['E2', 'E1']
    assert evidence['citations'] == evidence['sources']
    assert evidence['sources'][0]['evidence']['location']['page'] == 2
    before = {j.requirement_key: (j.status, j.basis_type, j.reason_code) for j in source.judgments}
    proposal = ask(api, case.id, '적용해줘', requirement_key='REQ-REGISTRATION',
                   user_input={'satisfies_requirement': True, 'evidence_held': True})['actions'][0]
    assert db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(
        QualificationJudgmentRun.preflight_case_id == case.id)) == 1
    response = api.post('/api/v1/copilot/actions/confirm', json={'confirmed': True, 'action': proposal})
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved['source_judgment_run_id'] == str(source.id)
    assert saved['result_judgment_run_id'] != str(source.id)
    assert saved['apply_to_profile'] is False
    for item in saved['result']['judgments']:
        if item['requirement_key'] == 'REQ-REGISTRATION':
            assert item['status'] == 'SATISFIED' and item['basis_type'] == 'USER_ANSWER'
        else:
            assert (item['status'], item['basis_type'], item['reason_code']) == before[item['requirement_key']]
    assert {j.requirement_key: (j.status, j.basis_type, j.reason_code) for j in source.judgments} == before
    latest = ask(api, case.id, '참여 가능해?')
    assert latest['product_state']['provenance']['judgment_run_id'] == saved['result_judgment_run_id']
    replay = api.post('/api/v1/copilot/actions/confirm', json={'confirmed': True, 'action': proposal})
    assert replay.status_code == 409 and replay.json()['error']['code'] == 'STALE_ACTION_CONTEXT'
    assert db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(
        QualificationJudgmentRun.preflight_case_id == case.id)) == 2


def test_chat_and_proposal_select_only_with_pending_edits(state, api, monkeypatch):
    db, case, _, _ = state
    db.autoflush = True
    db.get(Company, case.company_id).name = 'unsaved'
    monkeypatch.setattr(db, 'commit', lambda: pytest.fail('chat committed'))
    monkeypatch.setattr(db, 'flush', lambda: pytest.fail('chat flushed'))
    def select_only(conn, cursor, statement, *args):
        assert statement.lstrip().upper().startswith('SELECT'), statement
    connection = db.connection()
    event.listen(connection, 'before_cursor_execute', select_only)
    try:
        for message, extra in [('참여 가능해?', {}), ('프로필', {}), ('확인 필요', {}),
                               ('적용해', {'requirement_key': 'REQ-REGISTRATION', 'user_input': {'satisfies_requirement': True}})]:
            result = ask(api, case.id, message, **extra)
            assert result['external_processing_used'] is False
    finally:
        event.remove(connection, 'before_cursor_execute', select_only)


@pytest.mark.parametrize('field', ['company_id', 'notice_version_id', 'analysis_run_id', 'judgment_run_id'])
def test_tampered_expected_context_no_write(state, api, field):
    db, case, _, _ = state
    proposal = propose_answer(db, case.id, 'REQ-REGISTRATION', ActionInput(satisfies_requirement=True)).model_dump(mode='json')
    proposal['expected'][field] = str(uuid4())
    response = api.post('/api/v1/copilot/actions/confirm', json={'confirmed': True, 'action': proposal})
    assert response.status_code == 409 and response.json()['error']['code'] == 'STALE_ACTION_CONTEXT'
    assert db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(
        QualificationJudgmentRun.preflight_case_id == case.id)) == 1


@pytest.mark.parametrize('change,code', [('analysis', 'STALE_JUDGMENT'), ('profile', 'PROFILE_CHANGED_FULL_REJUDGMENT_REQUIRED'),
                                      ('nonaskable', 'REQUIREMENT_NOT_ASKABLE'), ('evidence', 'EVIDENCE_VERSION_MISMATCH')])
def test_context_changes_between_proposal_and_confirm(state, api, change, code):
    db, case, analysis, _ = state
    proposal = propose_answer(db, case.id, 'REQ-REGISTRATION', ActionInput(satisfies_requirement=True)).model_dump(mode='json')
    if change == 'analysis':
        db.add(QualificationAnalysisRun(notice_version_id=case.current_version_id, status='SUCCEEDED',
               contract_version=analysis.contract_version, analysis_kind=analysis.analysis_kind,
               input_fingerprint=analysis.input_fingerprint,
               created_at=analysis.created_at + timedelta(days=1)))
    elif change == 'profile':
        db.get(Company, case.company_id).region_name = 'changed'
    elif change == 'nonaskable':
        next(r for r in analysis.requirements if r.requirement_key == 'REQ-REGISTRATION').raw = '공동수급체 구성원 모두 등록업체이어야 한다.'
    else:
        analysis.evidence[0].notice_version_id = str(case.baseline_version_id)
    db.commit()
    response = api.post('/api/v1/copilot/actions/confirm', json={'confirmed': True, 'action': proposal})
    assert response.status_code == 409 and response.json()['error']['code'] == code
    assert db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(
        QualificationJudgmentRun.preflight_case_id == case.id)) == 1


def test_confirmation_is_explicit_and_profile_write_rejected(state, api):
    db, case, _, _ = state
    proposal = propose_answer(db, case.id, 'REQ-REGISTRATION', ActionInput(satisfies_requirement=True)).model_dump(mode='json')
    for confirmed in (False, None, 1, 'true'):
        assert api.post('/api/v1/copilot/actions/confirm', json={'confirmed': confirmed, 'action': proposal}).status_code == 422
    proposal['user_input']['apply_to_profile'] = True
    assert api.post('/api/v1/copilot/actions/confirm', json={'confirmed': True, 'action': proposal}).status_code == 422
    assert api.post('/api/v1/copilot/chat', json={'case_id': str(case.id), 'message': '적용해',
                    'requirement_key': 'REQ-REGISTRATION', 'user_input': {'satisfies_requirement': 'yes'}}).status_code == 422


def test_receipt_followup_and_stale_recovery_preserve_write_boundary(state, api):
    db, case, _, _ = state
    first = ask(api, case.id, '입찰 넣어도 돼?')
    context = {
        'visible_requirement_keys': first['reply_context']['visible_requirement_keys'],
        'last_read_receipt': first['reply_context']['last_read_receipt'],
        'last_response_intent': first['intent'],
    }
    selected = context['visible_requirement_keys'][1]
    result = ask(api, case.id, '두 번째 항목 근거', conversation_context=context)
    assert result['reply_context']['requirement_key'] == selected
    assert result['product_state']['requirement']['requirement_key'] == selected
    context['last_read_receipt']['provenance']['judgment_run_id'] = str(uuid4())
    before = db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(
        QualificationJudgmentRun.preflight_case_id == case.id))
    stale = ask(api, case.id, '두 번째 항목 적용해줘', conversation_context=context,
                user_input={'satisfies_requirement': False})
    assert stale['reply_context']['status'] == 'STALE_CONTEXT'
    assert stale['actions'] == [] and stale['reply_context']['requirement_key'] is None
    assert db.scalar(select(func.count()).select_from(QualificationJudgmentRun).where(
        QualificationJudgmentRun.preflight_case_id == case.id)) == before


def test_document_optin_privacy_hybrid_and_grounded_citations(state, api, monkeypatch):
    db, case, _, source = state
    sent = []
    class Embeddings(FakeEmbeddings):
        def embed_query(self, text):
            sent.append(text)
            return super().embed_query(text)
    embeddings = Embeddings()
    records = [_record(str(case.current_version_id), 'c1', '실적 1억원 이상이 필요합니다.'),
               _record(str(case.current_version_id), 'c2', '지역 제한은 서울입니다.')]
    for r in records:
        r.metadata.notice_id = str(case.notice_id)
        r.metadata.clause_label = '2'
        r.metadata.source_locations = ['p.2', 'p.3']
    index = VersionFaissIndex.build(records, embeddings=embeddings, embedding_model='fake')
    monkeypatch.setattr(grounded_flow, 'create_openai_embeddings', lambda: embeddings)
    monkeypatch.setattr(grounded_flow, 'load_or_build_version_index', lambda *a, **kw: index)

    def generate_grounded(question, hits):
        citations = [GroundedCitation(
            ref=f'S{position}', document_id=hit.metadata.document_id,
            document_name=hit.metadata.document_name,
            notice_version_id=hit.metadata.notice_version_id,
            chunk_id=hit.metadata.chunk_id, clause_label=hit.metadata.clause_label,
            page=hit.metadata.page, source_locations=hit.metadata.source_locations,
            quote=hit.text,
        ) for position, hit in enumerate(hits, start=1)]
        return GroundedDocumentAnswer(
            answer='실적 조건과 지역 제한의 공고문 근거입니다. [S1] [S2]',
            citations=citations,
            sources=citations,
        )

    monkeypatch.setattr(grounded_flow, 'generate_grounded_answer', generate_grounded)
    private = 'PRIVATE_PROFILE_AND_ASKBACK'
    for extra in ({}, {'public_document_question': '실적 조건 근거'}):
        response = ask(api, case.id, private, intent='DOCUMENT_QA', **extra)
        assert not response['external_processing_used'] and not sent
    response = ask(api, case.id, private, intent='DOCUMENT_QA', public_document_question='실적 조건 근거',
                   allow_external_processing=True, user_input={'satisfies_requirement': True, 'normalized_value': private})
    assert sent[0] == '실적 조건 근거' and all(private not in text for text in sent)
    assert all('Golden Demo Systems' not in text for text in sent)
    assert sent == ['실적 조건 근거']
    assert '실적 조건과 지역 제한의 공고문 근거입니다.' in response['answer']
    assert response['external_processing_used'] and response['product_state'] is None
    assert [s['ref'] for s in response['sources']] == ['S1', 'S2']
    assert [s['ref'] for s in response['citations']] == ['S1', 'S2']
    assert all(f"[{s['ref']}]" in response['answer'] for s in response['citations'])
    assert all(s['notice_version_id'] == str(case.current_version_id) for s in response['sources'])
    sent.clear()
    response = ask(api, case.id, '우리 회사 참여 가능해?', intent='DOCUMENT_QA',
                   public_document_question='실적 조건', allow_external_processing=True)
    assert response['intent'] == 'QUALIFICATION_SUMMARY' and not sent
    assert response['product_state']['overall_status'] == source.overall_status
    response = ask(api, case.id, '근거 보여줘', intent='DOCUMENT_QA', requirement_key='REQ-REGISTRATION',
                   public_document_question='실적 조건', allow_external_processing=True)
    assert response['intent'] == 'REQUIREMENT_EVIDENCE' and not sent
    index.notice_version_id = str(case.baseline_version_id)
    bad = api.post('/api/v1/copilot/chat', json={'case_id': str(case.id), 'message': '공고문',
                   'public_document_question': '실적 조건', 'allow_external_processing': True})
    assert bad.status_code == 502 and not sent
    index.notice_version_id = str(case.current_version_id)
    monkeypatch.setattr(grounded_flow, 'retrieve', lambda *a, **kw: [])
    empty = ask(api, case.id, '공고문', public_document_question='실적 조건', allow_external_processing=True)
    assert empty['sources'] == empty['citations'] == []
    assert '근거를 찾지 못했습니다' in empty['answer']
    assert '생성형 답변은 실행하지 않았습니다' in empty['answer']


def test_changed_notice_golden_and_revalidation_replay():
    seed = _seed_golden_case()
    try:
        with SessionLocal() as db:
            case = db.get(PreflightCase, seed['case_id'])
            current_id = case.current_version_id
            case.current_version_id = case.baseline_version_id
            db.commit()
            source = run_qualification_judgment(db, case_id=case.id, reference_date=date(2026, 9, 8))
            case.current_version_id = current_id
            db.commit()
            changed = get_changed_notice(db, case.id)
            assert changed.provenance.baseline.judgment_run_id == source.id
            assert changed.provenance.current.judgment_run_id is None
            assert changed.provenance.baseline.notice_version_id != changed.provenance.current.notice_version_id
            assert next(c for c in changed.changes if c.current_key == 'REQ-PERFORMANCE-AMOUNT').change_type == 'MODIFIED'
            proposal = RevalidationProposal(expected=changed.provenance)
            confirmed = ConfirmAction(confirmed=True, action=proposal)
            app.dependency_overrides[get_db] = lambda: db
            with TestClient(app) as client:
                read = ask(client, case.id, '변경공고에서 뭐 바뀌었어?')
                assert read['actions'] == []
                requested = ask(client, case.id, '전체 변경 요건 재검증해줘')
                assert requested['actions'] == [proposal.model_dump(mode='json')]
                assert read['product_state']['provenance']['current']['judgment_run_id'] is None
                response = client.post('/api/v1/copilot/actions/confirm', json=confirmed.model_dump(mode='json'))
                assert response.status_code == 200, response.text
            from apps.api.app.revalidation_schemas import QualificationRevalidationRead
            result = QualificationRevalidationRead.model_validate(response.json())
            # No source documents/evidence in this fixture: safe REVIEW, not reuse.
            assert result.revalidated_keys == []
            assert result.result.notice_version_id == current_id
            assert result.source_judgment_run_id == source.id
            assert get_changed_notice(db, case.id).provenance.current.judgment_run_id == result.result_judgment_run_id
            with pytest.raises(QualificationJudgmentError, match='제안 이후') as error:
                confirm_action(db, confirmed)
            assert error.value.code == 'STALE_ACTION_CONTEXT'
            assert db.scalar(select(func.count()).select_from(QualificationRevalidationRun).where(
                QualificationRevalidationRun.preflight_case_id == case.id)) == 1
            db.rollback()
    finally:
        app.dependency_overrides.pop(get_db, None)
        _cleanup(seed)


@pytest.mark.parametrize('changed_field', ['current_analysis', 'baseline_analysis', 'evidence'])
def test_changed_notice_stale_or_cross_version_rejected(changed_field):
    seed = _seed_golden_case()
    try:
        with SessionLocal() as db:
            case = db.get(PreflightCase, seed['case_id'])
            current_id = case.current_version_id
            case.current_version_id = case.baseline_version_id
            db.commit()
            run_qualification_judgment(db, case_id=case.id, reference_date=date(2026, 9, 8))
            case.current_version_id = current_id
            db.commit()
            expected = get_changed_notice(db, case.id).provenance
            if changed_field == 'evidence':
                from apps.api.app.analysis_models import QualificationEvidenceRecord
                db.add(QualificationEvidenceRecord(analysis_run_id=seed['current_analysis_id'], evidence_key='bad',
                       source_type='NOTICE_DOCUMENT', document_id=str(uuid4()),
                       notice_version_id=str(case.baseline_version_id), location={}, quote='wrong version'))
            else:
                old = db.get(QualificationAnalysisRun, seed[f'{changed_field}_id'])
                db.add(QualificationAnalysisRun(notice_version_id=old.notice_version_id, status='SUCCEEDED',
                       contract_version=old.contract_version, analysis_kind=old.analysis_kind,
                       input_fingerprint=old.input_fingerprint,
                       created_at=old.created_at + timedelta(days=1)))
            db.commit()
            with pytest.raises(QualificationJudgmentError) as error:
                confirm_action(db, ConfirmAction(confirmed=True, action=RevalidationProposal(expected=expected)))
            assert error.value.code == ('EVIDENCE_VERSION_MISMATCH' if changed_field == 'evidence' else 'STALE_ACTION_CONTEXT')
            assert db.scalar(select(func.count()).select_from(QualificationRevalidationRun).where(
                QualificationRevalidationRun.preflight_case_id == case.id)) == 0
            db.rollback()
    finally:
        _cleanup(seed)
