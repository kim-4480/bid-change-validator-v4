from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.api.app.copilot.chat import CopilotChatRequest
from apps.api.app.copilot.document_qa import answer_grounded_document_question
from bidengine.rag.answer import GroundedCitation, GroundedDocumentAnswer
from bidengine.rag.store import DocumentChunkHit, DocumentChunkMetadata


def hit(version: str, *, doc='doc-1', text='중소기업 확인서는 입찰 마감일까지 유효해야 합니다.'):
    return DocumentChunkHit(
        text=text,
        score=0.9,
        metadata=DocumentChunkMetadata(
            notice_id='notice-1', notice_version_id=version, version_number=1,
            document_id=doc, document_name='공고문.pdf', document_role='standard_notice',
            chunk_id=f'{doc}:CHUNK-0001', clause_label='제3조', page=3,
            source_locations=['p.3'],
        ),
    )


class FakeSession:
    def __init__(self, case_id, version_id):
        self.case_id = case_id
        self.version_id = version_id

    def get(self, model, key):
        assert key == self.case_id
        return SimpleNamespace(id=key, current_version_id=self.version_id)


def request(case_id, question='중소기업 확인서 제출 시점이 언제야?', *, allow=True):
    return CopilotChatRequest(
        case_id=case_id,
        message=question,
        intent='DOCUMENT_QA',
        public_document_question=question if allow else None,
        allow_external_processing=allow,
    )


def test_optin_required_before_index_or_generation(monkeypatch):
    case_id, version = uuid4(), uuid4()
    db = FakeSession(case_id, version)
    monkeypatch.setattr('apps.api.app.copilot.document_qa.load_or_build_version_index',
                        lambda *a, **k: pytest.fail('must not build index without opt-in'))
    monkeypatch.setattr('apps.api.app.copilot.document_qa.generate_grounded_answer',
                        lambda *a, **k: pytest.fail('must not generate without opt-in'))

    result = answer_grounded_document_question(db, request(case_id, allow=False))

    assert result.intent == 'DOCUMENT_QA'
    assert not result.external_processing_used
    assert result.sources == result.citations == []
    assert '외부 처리' in result.answer


def test_zero_hits_abstains_without_generation(monkeypatch):
    case_id, version = uuid4(), uuid4()
    db = FakeSession(case_id, version)
    monkeypatch.setattr('apps.api.app.copilot.document_qa.create_openai_embeddings', lambda: object())
    monkeypatch.setattr('apps.api.app.copilot.document_qa.load_or_build_version_index',
                        lambda *a, **k: SimpleNamespace(notice_version_id=str(version)))
    monkeypatch.setattr('apps.api.app.copilot.document_qa.retrieve', lambda *a, **k: [])
    monkeypatch.setattr('apps.api.app.copilot.document_qa.generate_grounded_answer',
                        lambda *a, **k: pytest.fail('must not generate when retrieval is empty'))

    result = answer_grounded_document_question(db, request(case_id))

    assert result.external_processing_used
    assert result.sources == result.citations == []
    assert '근거를 찾지 못했습니다' in result.answer
    assert '생성형 답변은 실행하지 않았습니다' in result.answer


def test_mixed_notice_version_hit_fails_closed(monkeypatch):
    case_id, version = uuid4(), uuid4()
    db = FakeSession(case_id, version)
    monkeypatch.setattr('apps.api.app.copilot.document_qa.create_openai_embeddings', lambda: object())
    monkeypatch.setattr('apps.api.app.copilot.document_qa.load_or_build_version_index',
                        lambda *a, **k: SimpleNamespace(notice_version_id=str(version)))
    monkeypatch.setattr('apps.api.app.copilot.document_qa.retrieve',
                        lambda *a, **k: [hit(str(uuid4()))])

    with pytest.raises(ValueError, match='hits do not match current notice version'):
        answer_grounded_document_question(db, request(case_id))


def test_only_cited_sources_are_exposed_and_rendered(monkeypatch):
    case_id, version = uuid4(), uuid4()
    db = FakeSession(case_id, version)
    hits = [hit(str(version), doc='doc-1'), hit(str(version), doc='doc-2', text='별도 예외 문구')]
    cited = GroundedCitation(
        ref='S1', document_id='doc-1', document_name='공고문.pdf',
        notice_version_id=str(version), chunk_id='doc-1:CHUNK-0001', clause_label='제3조',
        page=3, source_locations=['p.3'], quote=hits[0].text,
    )
    monkeypatch.setattr('apps.api.app.copilot.document_qa.create_openai_embeddings', lambda: object())
    monkeypatch.setattr('apps.api.app.copilot.document_qa.load_or_build_version_index',
                        lambda *a, **k: SimpleNamespace(notice_version_id=str(version)))
    monkeypatch.setattr('apps.api.app.copilot.document_qa.retrieve', lambda *a, **k: hits)
    monkeypatch.setattr('apps.api.app.copilot.document_qa.generate_grounded_answer', lambda *a, **k:
        GroundedDocumentAnswer(answer='입찰 마감일까지 유효해야 합니다. [S1]', citations=[cited], sources=[cited]))

    result = answer_grounded_document_question(db, request(case_id))

    assert len(result.sources) == len(result.citations) == 1
    assert result.sources[0].document_id == 'doc-1'
    assert result.citations[0].ref == 'S1'
    assert '[S1]' in result.answer
    assert '입찰 마감일까지 유효해야 합니다.' in result.answer
    assert 'doc-2' not in result.answer


def test_uncited_generated_text_is_not_exposed(monkeypatch):
    case_id, version = uuid4(), uuid4()
    db = FakeSession(case_id, version)
    one = hit(str(version))
    monkeypatch.setattr('apps.api.app.copilot.document_qa.create_openai_embeddings', lambda: object())
    monkeypatch.setattr('apps.api.app.copilot.document_qa.load_or_build_version_index',
                        lambda *a, **k: SimpleNamespace(notice_version_id=str(version)))
    monkeypatch.setattr('apps.api.app.copilot.document_qa.retrieve', lambda *a, **k: [one])
    monkeypatch.setattr('apps.api.app.copilot.document_qa.generate_grounded_answer', lambda *a, **k:
        GroundedDocumentAnswer(answer='확실히 참가 가능합니다.', citations=[], sources=[]))

    result = answer_grounded_document_question(db, request(case_id))

    assert result.sources == result.citations == []
    assert '확실히 참가 가능합니다' not in result.answer
    assert '답을 확정할 수 없습니다' in result.answer
    assert '검증 가능한 공고문 인용이 없어' in result.answer


def test_company_eligibility_question_never_uses_document_generation(monkeypatch):
    case_id, version = uuid4(), uuid4()
    db = FakeSession(case_id, version)
    monkeypatch.setattr('apps.api.app.copilot.document_qa.load_or_build_version_index',
                        lambda *a, **k: pytest.fail('eligibility question must use product truth'))

    result = answer_grounded_document_question(
        db, request(case_id, '우리 회사 참가 가능해?')
    )

    assert not result.external_processing_used
    assert '저장된 판정 결과' in result.answer
    assert result.sources == result.citations == []
