"""Composed PR A checks with fake product reads; no database or model calls.

Use --noconftest to avoid the repository's database-seeding autouse fixture.
"""

from contextlib import nullcontext
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from bidengine.contracts import Evidence, QualificationRequirement
from apps.api.app.ask_back_schemas import QualificationQuestionRead
from apps.api.app.copilot import chat as flow
from apps.api.app.copilot.context import ConversationContext
from apps.api.app.copilot.contracts import (
    AnswerProposal, ProductProvenance, QualificationSummary, RequiredChecksResult,
    RequirementEvidenceResult, RequirementJudgmentSummary,
)
from apps.api.app.copilot.presentation import Presentation, Reason, render_answer
from apps.api.app.copilot.source_map import SourceMap, cited_sources
from apps.api.app.database import get_db
from apps.api.app.main import app
from apps.api.app.qualification.judgment import QualificationJudgmentError


@pytest.fixture
def local(monkeypatch):
    provenance = ProductProvenance(
        case_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4(), version_number=2,
        company_id=uuid4(), analysis_run_id=uuid4(), judgment_run_id=uuid4(),
        analysis_status="PARTIAL", rule_version="test-rule",
    )
    evidence = Evidence(
        evidence_key="E1", source_type="NOTICE_DOCUMENT", document_id=str(uuid4()),
        notice_version_id=str(provenance.notice_version_id), chunk_id="chunk-1",
        location={"page": 2, "clause_label": "3", "display": "p.2, p.3"}, quote="등록 및 소재지 요건",
        source_sha256="a" * 64, extracted_text_sha256="b" * 64,
    )
    requirements = [QualificationRequirement(
        requirement_key=key, notice_version_id=str(provenance.notice_version_id), type=kind,
        raw=raw, evidence_keys=["E1"],
    ) for key, kind, raw in (("R1", "REGISTRATION_CERTIFICATION", "등록 요건"), ("R2", "REGION", "지역 요건"))]
    judgments = [RequirementJudgmentSummary(
        judgment_key=f"J{i}", preflight_case_id=str(provenance.case_id), notice_version_id=str(provenance.notice_version_id),
        requirement_key=r.requirement_key, status="UNKNOWN", basis_type="NONE",
        reason_code="UNSUPPORTED_REQUIREMENT" if i == 0 else "INSUFFICIENT_DATA", requirement_evidence_keys=["E1"],
        type=r.type, raw=r.raw,
    ) for i, r in enumerate(requirements)]
    summary = QualificationSummary(provenance=provenance, overall_status="insufficient_data", analysis_status="PARTIAL",
                                   judgment_counts={"UNKNOWN": 2, "SATISFIED": 0, "UNSATISFIED": 0}, judgments=judgments)
    state = SimpleNamespace(summary=summary, requirements=requirements, evidence=evidence, calls=[], proposals=[])

    class FakeSession:
        no_autoflush = nullcontext()

        def get(self, model, key):
            assert key == provenance.case_id
            return SimpleNamespace(id=key, current_version_id=provenance.notice_version_id)

        def commit(self):
            pytest.fail("chat must not commit")

        def flush(self):
            pytest.fail("chat must not flush")

    state.db = FakeSession()

    def bundles(db, case_id, keys):
        state.calls.append(tuple(keys))
        return [RequirementEvidenceResult(provenance=state.summary.provenance, requirement=r,
                                           evidence=[state.evidence.model_copy(deep=True)])
                for key in keys for r in state.requirements if r.requirement_key == key]

    def checks(*args):
        return RequiredChecksResult(provenance=state.summary.provenance, questions=[QualificationQuestionRead(
            requirement_key=r.requirement_key, requirement_type=r.type, question=f"{r.raw}을 확인해 주세요.",
            raw_requirement=r.raw, askable=r.requirement_key == "R2",
            askability_reason_code="ASKABLE_SIMPLE_FACT" if r.requirement_key == "R2" else "UNSUPPORTED_REQUIREMENT",
        ) for r in state.requirements])

    def proposal(db, case_id, key, user_input):
        state.proposals.append((key, user_input))
        return AnswerProposal(expected=state.summary.provenance, requirement_key=key, user_input=user_input)

    monkeypatch.setattr(flow, "get_qualification_summary", lambda *args: state.summary.model_copy(deep=True))
    monkeypatch.setattr(flow, "get_explanation_evidence", bundles)
    monkeypatch.setattr(flow, "get_requirement_evidence", lambda db, case_id, key: bundles(db, case_id, [key])[0])
    monkeypatch.setattr(flow, "get_required_checks", checks)
    monkeypatch.setattr(flow, "propose_answer", proposal)
    monkeypatch.setattr(flow, "create_openai_embeddings", lambda: pytest.fail("private chat must not reach embeddings"))
    app.dependency_overrides[get_db] = lambda: state.db
    state.api = TestClient(app)
    try:
        yield state
    finally:
        state.api.close()
        app.dependency_overrides.pop(get_db, None)


def ask(local, message, **kwargs):
    response = local.api.post("/api/v1/copilot/chat", json={"case_id": str(local.summary.provenance.case_id), "message": message, **kwargs})
    assert response.status_code == 200, response.text
    return response.json()


def hints(response):
    return {"visible_requirement_keys": response["reply_context"]["visible_requirement_keys"],
            "last_read_receipt": response["reply_context"]["last_read_receipt"],
            "last_response_intent": response["intent"], "context_revision": 7}


@pytest.fixture
def real_proposals(local, monkeypatch):
    """Exercise the actual askability/rule boundary using only fake product reads."""
    from apps.api.app.copilot import actions
    from bidengine.judgment.rules import RULE_VERSION
    local.summary.provenance.rule_version = RULE_VERSION
    monkeypatch.setattr(actions, "get_required_checks", flow.get_required_checks)
    monkeypatch.setattr(flow, "propose_answer", actions.propose_answer)
    return local


@pytest.mark.parametrize("ordinal", ["2번째", "2 번째", "2 번 째", "두 번째", "두번째"])
@pytest.mark.parametrize("explicit_focus", [None, "R2"])
def test_out_of_range_ordinal_never_falls_back_to_only_askable_target(real_proposals, ordinal, explicit_focus):
    first = ask(real_proposals, "근거", requirement_key="R2")
    result = ask(real_proposals, f"{ordinal} 적용해줘", requirement_key=explicit_focus,
                 conversation_context=hints(first), user_input={"satisfies_requirement": False})
    assert result["reply_context"]["status"] == "NEEDS_TARGET"
    assert result["reply_context"]["requirement_key"] is None
    assert result["actions"] == []


@pytest.mark.parametrize("ordinal", ["2번째", "2 번째", "2 번 째", "두 번째", "두번째"])
def test_valid_ordinal_passes_real_proposal_boundary(real_proposals, ordinal):
    first = ask(real_proposals, "참여 가능해?")
    result = ask(real_proposals, f"{ordinal} 적용해줘", conversation_context=hints(first),
                 user_input={"satisfies_requirement": False, "evidence_held": False})
    proposal = result["actions"][0]
    assert proposal["requirement_key"] == "R2"
    assert proposal["user_input"]["satisfies_requirement"] is False
    assert proposal["user_input"]["evidence_held"] is False


@pytest.mark.parametrize("ordinal", ["3번째", "3 번 째", "세 번째", "몇 번째", "?번째", "2.5번째"])
def test_invalid_ordinal_in_two_item_list_never_uses_focus(real_proposals, ordinal):
    first = ask(real_proposals, "참여 가능해?")
    result = ask(real_proposals, f"{ordinal} 적용해줘", requirement_key="R2", conversation_context=hints(first),
                 user_input={"satisfies_requirement": True})
    assert result["reply_context"]["status"] == "NEEDS_TARGET"
    assert result["actions"] == [] and result["reply_context"]["requirement_key"] is None


@pytest.mark.parametrize("key,rule,code", [("R1", None, "REQUIREMENT_NOT_ASKABLE"), ("R2", "old-rule", "STALE_ACTION_CONTEXT")])
def test_real_proposal_keeps_backend_rejections(real_proposals, key, rule, code):
    if rule:
        real_proposals.summary.provenance.rule_version = rule
    response = real_proposals.api.post("/api/v1/copilot/chat", json={
        "case_id": str(real_proposals.summary.provenance.case_id), "message": "적용해줘",
        "requirement_key": key, "user_input": {"satisfies_requirement": True},
    })
    assert response.status_code == 409 and response.json()["error"]["code"] == code


@pytest.mark.parametrize("message", ["입찰 넣어도 돼?", "우리 회사 지원할 수 있어?", "참여 가능해?", "입찰 해도 돼?"])
def test_existing_request_and_natural_variants_use_product_truth(local, message):
    response = ask(local, message)
    assert response["intent"] == "QUALIFICATION_SUMMARY"
    assert response["product_state"] == local.summary.model_dump(mode="json")
    assert response["presentation"]["conclusion"] in response["answer"]
    assert "확정할 수 없습니다" in response["answer"]
    assert not response["external_processing_used"]


def test_shared_source_joins_reasons_answer_and_citations_once(local):
    response = ask(local, "참여 가능해?")
    assert len(local.calls) == 1
    assert [s["ref"] for s in response["sources"]] == ["S1"]
    assert [r["evidence_refs"] for r in response["presentation"]["reasons"]] == [["S1"], ["S1"]]
    assert response["citations"] == response["sources"]
    assert response["sources"][0]["evidence"] == local.evidence.model_dump(mode="json")
    assert "조항 3" in response["answer"] and "p.2, p.3" in response["answer"]
    assert "일부 문서가 분석되지" not in response["answer"]
    assert "회사정보를 입력하지" not in response["answer"]


def test_ordinal_uses_visible_order_not_new_backend_order(local):
    first = ask(local, "참여 가능해?")
    local.summary.judgments.reverse()
    local.calls.clear()
    followup = ask(local, "두 번째 항목 근거 보여줘", conversation_context=hints(first))
    assert followup["reply_context"]["status"] == "RESOLVED"
    assert followup["reply_context"]["requirement_key"] == "R2"
    assert followup["reply_context"]["visible_requirement_keys"] == ["R2"]
    assert local.calls == [("R2",)]


@pytest.mark.parametrize("field", ["case_id", "notice_version_id", "analysis_run_id", "judgment_run_id", "company_id", "rule_version", "analysis_status"])
def test_stale_receipt_is_normal_control_flow_without_target_or_proposal(local, field):
    context = hints(ask(local, "참여 가능해?"))
    context["last_read_receipt"]["provenance"][field] = ("other-rule" if field == "rule_version" else
                                                        "SUCCEEDED" if field == "analysis_status" else str(uuid4()))
    local.calls.clear()
    response = ask(local, "두 번째 항목에 적용해줘", conversation_context=context,
                   user_input={"satisfies_requirement": False, "evidence_held": False})
    assert response["reply_context"]["status"] == "STALE_CONTEXT"
    assert response["reply_context"]["requirement_key"] is None
    assert response["actions"] == response["sources"] == []
    assert not local.calls and not local.proposals
    assert "검토 기준이 바뀌었습니다" in response["answer"]


@pytest.mark.parametrize("message,extra,status", [
    ("두 번째 근거", {}, "NEEDS_CONTEXT"), ("왜?", {}, "NEEDS_CONTEXT"), ("그 조건 근거", {}, "NEEDS_CONTEXT"),
    ("근거", {"requirement_key": "other-case-key"}, "NEEDS_TARGET"),
])
def test_missing_or_invalid_context_never_selects_a_target(local, message, extra, status):
    response = ask(local, message, **extra)
    assert response["reply_context"]["status"] == status
    assert response["actions"] == [] and local.calls == []


@pytest.mark.parametrize("message,key", [("두 번째 근거", "R1"), ("그 조건 근거", None), ("0번째 근거", None), ("101번째 근거", None), ("첫 번째와 두 번째 근거", None), ("-1번째 근거", None), ("열두 번째 근거", None)])
def test_conflicting_or_ambiguous_references_ask_for_selection(local, message, key):
    context = hints(ask(local, "참여 가능해?"))
    response = ask(local, message, requirement_key=key, conversation_context=context)
    assert response["reply_context"]["status"] == "NEEDS_TARGET"
    assert response["reply_context"]["requirement_key"] is None


def test_why_retains_focus_and_proposal_preserves_false_without_execution(local):
    first = ask(local, "근거", requirement_key="R2")
    why = ask(local, "왜?", requirement_key="R2", conversation_context=hints(first))
    assert [r["requirement_key"] for r in why["presentation"]["reasons"]] == ["R2"]
    response = ask(local, "그 조건에 반영해줘", requirement_key="R2", conversation_context=hints(why),
                   user_input={"satisfies_requirement": False, "evidence_held": False})
    assert response["actions"][0]["user_input"]["satisfies_requirement"] is False
    assert response["actions"][0]["user_input"]["evidence_held"] is False
    assert "아직 저장하지" in response["answer"]
    assert ask(local, "응")["actions"] == []


def test_nonaskable_and_askable_explanations_have_different_next_actions(local):
    for key, kind in (("R1", "VIEW_EVIDENCE"), ("R2", "ANSWER_REQUIREMENT")):
        result = ask(local, "무엇을 확인해야 해?", requirement_key=key)
        assert result["presentation"]["next_action"]["kind"] == kind
        assert result["reply_context"]["visible_requirement_keys"] == [key]


def test_missing_source_in_composed_presentation_fails_before_response(local, monkeypatch):
    original = flow.present_product
    def bad(*args, **kwargs):
        result = original(*args, **kwargs)
        result.reasons[0].evidence_refs.append("nonexistent")
        return result
    monkeypatch.setattr(flow, "present_product", bad)
    response = local.api.post("/api/v1/copilot/chat", json={"case_id": str(local.summary.provenance.case_id), "message": "참여 가능해?"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "COPILOT_SOURCE_MAPPING_INVALID"
    assert "answer" not in response.json()


def test_read_bundle_retries_once_and_never_combines_different_provenance(local, monkeypatch):
    original = flow.get_explanation_evidence
    attempts = []
    def changed(*args):
        attempts.append(1)
        result = original(*args)
        for bundle in result:
            bundle.provenance = bundle.provenance.model_copy(update={"judgment_run_id": uuid4()})
        return result
    monkeypatch.setattr(flow, "get_explanation_evidence", changed)
    result = ask(local, "참여 가능해?")
    assert len(attempts) == 2
    assert result["reply_context"]["status"] == "STALE_CONTEXT"
    assert result["sources"] == result["actions"] == []
    assert result["product_state"] is None


def test_new_analysis_without_judgment_recovers_stale_followup(local, monkeypatch):
    context = hints(ask(local, "참여 가능해?"))
    def stale(*args):
        raise QualificationJudgmentError("STALE_JUDGMENT", "최신 분석 판정 필요")
    monkeypatch.setattr(flow, "get_qualification_summary", stale)
    result = ask(local, "두 번째 근거", conversation_context=context)
    assert result["reply_context"]["status"] == "STALE_CONTEXT"
    assert result["reply_context"]["last_read_receipt"] is None


def test_source_identity_keeps_versions_origins_and_locators_distinct(local):
    mapping = SourceMap()
    first = flow.ProductSource(ref="S1", evidence=local.evidence)
    second = first.model_copy(deep=True)
    second.evidence.notice_version_id = str(uuid4())
    document = flow.DocumentSource(ref="S1", document_id=local.evidence.document_id, document_name="공고문",
                                  notice_version_id=local.evidence.notice_version_id, chunk_id="chunk-1",
                                  quote=local.evidence.quote, page=2, source_locations=["p.2", "p.3"])
    ids = [mapping.add(s) for s in (first, second, document)]
    presentation = Presentation(conclusion="원문", reasons=[Reason(text="관련 근거", evidence_refs=ids)])
    sources = mapping.finalize(presentation)
    answer = render_answer(presentation, sources)
    assert [s.ref for s in sources] == ["S1", "S2", "S3"]
    assert cited_sources(answer, presentation, sources) == sources
    with pytest.raises(QualificationJudgmentError, match="근거 연결"):
        cited_sources(answer + " [S99]", presentation, sources)


def test_quote_literal_reference_is_not_forged_citation(local):
    local.evidence.quote += " 원문 식별자 [S99]"
    response = ask(local, "근거", requirement_key="R1")
    assert "[S99]" in response["sources"][0]["evidence"]["quote"]
    assert "[S99]" not in response["answer"] and "［S99］" in response["answer"]


@pytest.mark.parametrize("value", [
    {"visible_requirement_keys": ["R1", "R1"]}, {"visible_requirement_keys": [""]},
    {"visible_requirement_keys": [str(i) for i in range(101)]}, {"context_revision": True},
    {"context_revision": -1}, {"source_page": "ADMIN"}, {"focused_requirement_key": "R1"},
    {"last_read_receipt": {"kind": "product", "provenance": {}}},
])
def test_context_input_boundary(value):
    with pytest.raises(ValidationError):
        ConversationContext.model_validate(value)


def test_read_bundle_can_recover_once_without_leaking_first_attempt(local, monkeypatch):
    original = flow.get_explanation_evidence
    attempts = []
    def changing(*args):
        result = original(*args)
        if not attempts:
            result[0].provenance = result[0].provenance.model_copy(update={"judgment_run_id": uuid4()})
            result[0].evidence[0].quote = "첫 조회에서 버려야 할 원문"
        attempts.append(1)
        return result
    monkeypatch.setattr(flow, "get_explanation_evidence", changing)
    result = ask(local, "참여 가능해?")
    assert len(attempts) == 2 and result["reply_context"]["status"] == "RESOLVED"
    assert "버려야 할 원문" not in result["answer"]


def test_direct_action_with_stale_receipt_does_not_rebind_explicit_key(local):
    context = hints(ask(local, "참여 가능해?"))
    context["last_read_receipt"]["provenance"]["judgment_run_id"] = str(uuid4())
    response = ask(local, "반영해줘", requirement_key="R2", conversation_context=context,
                   user_input={"satisfies_requirement": True})
    assert response["reply_context"]["status"] == "STALE_CONTEXT" and not local.proposals


@pytest.mark.parametrize("message", ["반영해줘", "그 조건에 반영해줘"])
@pytest.mark.parametrize("code", ["STALE_JUDGMENT", "CURRENT_JUDGMENT_REQUIRED", "STALE_ACTION_CONTEXT"])
def test_receipt_backed_action_backend_stale_is_http_200(local, monkeypatch, message, code):
    context = hints(ask(local, "근거", requirement_key="R2"))
    def stale(*args):
        raise QualificationJudgmentError(code, "기준이 바뀌었습니다.", status_code=409)
    monkeypatch.setattr(flow, "get_qualification_summary", stale)
    response = ask(local, message, requirement_key="R2", conversation_context=context,
                   user_input={"satisfies_requirement": True})
    assert response["reply_context"]["status"] == "STALE_CONTEXT"
    assert response["actions"] == response["sources"] == []
    assert response["reply_context"]["requirement_key"] is None and not local.proposals


@pytest.mark.parametrize("message,with_receipt", [("반영해줘", False), ("그 조건에 반영해줘", False), ("참여 가능해?", True)])
def test_independent_backend_stale_keeps_original_http_error(local, monkeypatch, message, with_receipt):
    context = hints(ask(local, "참여 가능해?")) if with_receipt else {"context_revision": 1}
    def stale(*args):
        raise QualificationJudgmentError("STALE_JUDGMENT", "판정 기준을 확인해 주세요.", status_code=409)
    monkeypatch.setattr(flow, "get_qualification_summary", stale)
    response = local.api.post("/api/v1/copilot/chat", json={
        "case_id": str(local.summary.provenance.case_id), "message": message,
        "requirement_key": "R2", "conversation_context": context,
        "user_input": {"satisfies_requirement": True},
    })
    assert response.status_code == 409 and response.json()["error"]["code"] == "STALE_JUDGMENT"


def test_real_proposal_rule_stale_with_receipt_is_control_result(real_proposals):
    real_proposals.summary.provenance.rule_version = "old-rule"
    first = ask(real_proposals, "근거", requirement_key="R2")
    response = ask(real_proposals, "반영해줘", requirement_key="R2", conversation_context=hints(first),
                   user_input={"satisfies_requirement": True})
    assert response["reply_context"]["status"] == "STALE_CONTEXT" and response["actions"] == []


def test_real_proposal_askability_error_is_not_masked_by_receipt(real_proposals):
    first = ask(real_proposals, "근거", requirement_key="R1")
    response = real_proposals.api.post("/api/v1/copilot/chat", json={
        "case_id": str(real_proposals.summary.provenance.case_id), "message": "반영해줘",
        "requirement_key": "R1", "conversation_context": hints(first), "user_input": {"satisfies_requirement": True},
    })
    assert response.status_code == 409 and response.json()["error"]["code"] == "REQUIREMENT_NOT_ASKABLE"


@pytest.mark.parametrize("message", ["그 등록은 되어 있어", "그 등록은 안 되어 있어", "그 조건은 충족하지 않아"])
def test_natural_statements_do_not_invent_action_input(local, message):
    first = ask(local, "근거", requirement_key="R1")
    response = ask(local, message, requirement_key="R1", conversation_context=hints(first))
    assert response["intent"] == "ACTION_REQUEST"
    assert response["actions"] == [] and not local.proposals
    assert "명시적인 사용자 답변" in response["answer"]


@pytest.mark.parametrize("message", [
    "재검증하지 마", "재검증 취소", "취소", "재검증하지 않을래", "재검증하고 싶지 않아",
    "재검증이 뭐야?", "재검증 무슨 뜻", "재검증해야 해?", "재검증 설명해줘", "재검증",
    "다시 검토하지 마", "다시 검토해야 해?", "반영하지 마", "적용이 뭐야?",
])
@pytest.mark.parametrize("explicit_action", [False, True])
def test_cancel_and_explanation_never_create_proposal(local, monkeypatch, message, explicit_action):
    def unexpected(*args):
        pytest.fail("cancel/explanation must not enter product/action execution reads")
    for name in ("get_changed_notice", "get_qualification_summary", "propose_answer"):
        monkeypatch.setattr(flow, name, unexpected)
    extra = {"intent": "ACTION_REQUEST", "user_input": {"satisfies_requirement": True}} if explicit_action else {}
    response = ask(local, message, requirement_key="R2", **extra)
    assert response["actions"] == [] and response["product_state"] is None
    assert response["answer"] and not response["external_processing_used"]
    assert response["presentation"]["next_action"] is None


def test_negative_requirement_fact_can_still_produce_real_answer_proposal(real_proposals):
    first = ask(real_proposals, "근거", requirement_key="R2")
    response = ask(real_proposals, "그 조건은 충족하지 않아", requirement_key="R2", conversation_context=hints(first),
                   user_input={"satisfies_requirement": False})
    assert response["actions"][0]["action_type"] == "ANSWER_REQUIREMENT"
    assert response["actions"][0]["user_input"]["satisfies_requirement"] is False


@pytest.mark.parametrize("message", ["하지 마", "하지 않을래", "취소", "뭐야", "무슨 뜻", "해야 해?"])
def test_short_cancel_or_question_does_not_apply_carried_answer_input(real_proposals, message):
    first = ask(real_proposals, "근거", requirement_key="R2")
    response = ask(real_proposals, message, requirement_key="R2", conversation_context=hints(first),
                   user_input={"satisfies_requirement": True})
    assert response["actions"] == [] and response["presentation"]["next_action"] is None


@pytest.mark.parametrize("verb", ["적용", "반영", "저장"])
@pytest.mark.parametrize("ending", ["하지 마", "해 주지 마", "하지 말아줘", "해 주지 않았으면 해", "하지 않을래"])
@pytest.mark.parametrize("explicit_intent", [None, "QUALIFICATION_SUMMARY"])
def test_negation_of_action_verb_never_proposes(real_proposals, verb, ending, explicit_intent):
    first = ask(real_proposals, "근거", requirement_key="R2")
    result = ask(real_proposals, f"그 답은 {verb}{ending}", requirement_key="R2", intent=explicit_intent,
                 conversation_context=hints(first), user_input={"satisfies_requirement": True})
    assert result["actions"] == [] and result["product_state"] is None
    assert "새 작업 제안을 만들지 않았습니다" in result["answer"]


@pytest.mark.parametrize("message", ["적용 안 된 이유 알려줘", "왜 반영되지 않았어?", "저장되지 않은 이유 알려줘"])
def test_negative_action_history_question_reads_without_inventing_cause(real_proposals, message):
    result = ask(real_proposals, message, user_input={"satisfies_requirement": True})
    assert result["intent"] == "QUALIFICATION_SUMMARY" and result["actions"] == []
    assert result["product_state"] == real_proposals.summary.model_dump(mode="json")
    assert "미처리 이유는 단정할 수 없습니다" in result["answer"]
    assert "새 작업 제안을 만들지 않았습니다" not in result["answer"]


@pytest.mark.parametrize("message", [
    "재검증 결과 우리 회사 참여 가능해?", "재검증 후 참여 가능해졌어?", "재검증 결과가 뭐야?",
    "재검증은 언제 했어?", "다시 판정한 결과 보여줘", "왜 미달이야?", "현재 결과 보여줘",
])
@pytest.mark.parametrize("explicit_intent", [None, "QUALIFICATION_SUMMARY", "ACTION_REQUEST"])
def test_product_result_question_wins_over_action_nouns_and_carried_input(real_proposals, message, explicit_intent):
    result = ask(real_proposals, message, intent=explicit_intent, user_input={"satisfies_requirement": True})
    assert result["intent"] == "QUALIFICATION_SUMMARY" and result["actions"] == []
    assert result["product_state"] == real_proposals.summary.model_dump(mode="json")
    assert result["presentation"]["conclusion"] in result["answer"]


@pytest.mark.parametrize("message", ["재검증이 뭐야?", "왜 재검증해야 해?"])
def test_action_definition_is_readonly_even_with_input(real_proposals, message):
    result = ask(real_proposals, message, intent="ACTION_REQUEST", requirement_key="R2", user_input={"satisfies_requirement": True})
    assert result["actions"] == [] and result["product_state"] is None
    assert "재검증은 변경된 참가자격 요건 전체" in result["answer"]


@pytest.mark.parametrize("message", ["반영해줘", "적용해주세요", "그 조건은 충족하지 않아"])
def test_valid_answer_has_exactly_one_real_proposal(real_proposals, message):
    first = ask(real_proposals, "근거", requirement_key="R2")
    result = ask(real_proposals, message, requirement_key="R2", conversation_context=hints(first),
                 user_input={"satisfies_requirement": False})
    assert len(result["actions"]) == 1
    assert result["actions"][0]["action_type"] == "ANSWER_REQUIREMENT"
    assert result["actions"][0]["user_input"]["satisfies_requirement"] is False


@pytest.mark.parametrize("message", ["응", "잠깐 보류", "알겠어"])
def test_payload_without_execution_or_fact_statement_never_proposes(real_proposals, message):
    result = ask(real_proposals, message, intent="ACTION_REQUEST", requirement_key="R2", user_input={"satisfies_requirement": True})
    assert result["actions"] == []


@pytest.fixture
def changed_notice(local, monkeypatch):
    from apps.api.app.copilot.actions import ChangedNoticeResult
    from apps.api.app.copilot.contracts import RevalidationProvenance, VersionState
    from bidengine.diff.requirement_diff import RequirementChange
    p = local.summary.provenance
    baseline = VersionState(notice_version_id=uuid4(), version_number=1, analysis_run_id=uuid4(),
                            analysis_status="SUCCEEDED", judgment_run_id=uuid4())
    current = VersionState(notice_version_id=p.notice_version_id, version_number=2,
                           analysis_run_id=p.analysis_run_id, analysis_status="PARTIAL", judgment_run_id=p.judgment_run_id)
    old = local.requirements[1].model_copy(update={"notice_version_id": str(baseline.notice_version_id), "raw": "이전 지역 요건"})
    changed = ChangedNoticeResult(provenance=RevalidationProvenance(
        case_id=p.case_id, notice_id=p.notice_id, company_id=p.company_id, baseline=baseline, current=current, rule_version=p.rule_version,
    ), changes=[RequirementChange(change_type="ADDED", identity="registration", current_key="R1", current=local.requirements[0]),
                RequirementChange(change_type="MODIFIED", identity="region", baseline_key="R2", current_key="R2",
                                   baseline=old, current=local.requirements[1])])
    monkeypatch.setattr(flow, "get_changed_notice", lambda *args: changed.model_copy(deep=True))
    return changed


@pytest.mark.parametrize("message", ["재검증해줘", "전체 변경 요건 재검증해줘", "다시 검토해줘",
                                     "전체 변경 요건 다시 재검증해줘", "전체 변경 요건 다시 검증하고 싶어", "전체 다시 봐줘"])
def test_revalidation_execution_requires_valid_backend_context(local, changed_notice, monkeypatch, message):
    response = ask(local, message)
    assert len(response["actions"]) == 1
    assert response["actions"][0]["action_type"] == "REVALIDATE"
    assert response["actions"][0]["expected"] == changed_notice.provenance.model_dump(mode="json")
    def invalid(*args):
        raise QualificationJudgmentError("BASELINE_VERSION_REQUIRED", "기준 버전이 없습니다.", status_code=409)
    monkeypatch.setattr(flow, "get_changed_notice", invalid)
    failed = local.api.post("/api/v1/copilot/chat", json={"case_id": str(local.summary.provenance.case_id), "message": message})
    assert failed.status_code == 409 and failed.json()["error"]["code"] == "BASELINE_VERSION_REQUIRED"
    assert "actions" not in failed.json()


@pytest.mark.parametrize("message", ["그 조건만 재검증해줘", "첫 번째만 재검증해줘", "선택한 요건 재검증해줘", "재검증해줘"])
def test_focused_revalidation_needs_whole_scope_request(local, changed_notice, message):
    first = ask(local, "뭐가 바뀌었어?", requirement_key="R1")
    assert first["actions"] == []
    limited = ask(local, message, requirement_key="R1", conversation_context=hints(first))
    assert limited["actions"] == []
    assert "요건 전체" in limited["answer"]
    assert limited["presentation"]["next_action"] is None
    whole = ask(local, "전체 변경 요건 재검증해줘", requirement_key="R1", conversation_context=hints(limited))
    assert [r["requirement_key"] for r in whole["presentation"]["reasons"]] == ["R1", "R2"]
    assert whole["actions"][0]["expected"] == changed_notice.provenance.model_dump(mode="json")
    assert "요건 전체" in whole["answer"]


@pytest.mark.parametrize("message", ["지역 조건만 재검증해줘", "등록 요건 재검증해줘", "선택한 항목 재검증해줘", "전체 중 한 개만 재검증해줘"])
def test_limited_revalidation_without_explicit_key_has_no_whole_scope_proposal(local, changed_notice, message):
    response = ask(local, message)
    assert response["actions"] == [] and "요건 전체" in response["answer"]


@pytest.mark.parametrize("message", [
    "전체 말고 그 조건만 재검증해줘", "전체 말고 그 조건 재검증해줘", "지역 요건 제외하고 전체 재검증해줘",
    "R2 빼고 전체 다시 봐줘", "일부만 다시 검증하고 싶어", "전체는 아니고 선택한 요건 재검증해줘",
])
@pytest.mark.parametrize("explicit_intent", [None, "QUALIFICATION_SUMMARY"])
def test_scope_exclusion_overrides_whole_word_and_read_hint(local, changed_notice, message, explicit_intent):
    first = ask(local, "뭐가 바뀌었어?", requirement_key="R2")
    result = ask(local, message, intent=explicit_intent, requirement_key="R2", conversation_context=hints(first))
    assert result["actions"] == [] and result["presentation"]["next_action"] is None
    assert "일부 요건을 제외하거나 한 요건만 선택해서 실행할 수 없습니다" in result["answer"]


@pytest.mark.parametrize("intent", ["QUALIFICATION_SUMMARY", "REQUIRED_CHECKS", "REQUIREMENT_EVIDENCE", "CHANGED_NOTICE", "DOCUMENT_QA"])
@pytest.mark.parametrize("message", ["전체 변경 요건 재검증해줘", "재검증 결과 확인"])
def test_explicit_read_intent_never_creates_revalidation_proposal(local, changed_notice, intent, message):
    result = ask(local, message, intent=intent, requirement_key="R2")
    assert result["intent"] == intent and result["actions"] == []


def test_changed_notice_read_never_proposes_execution(local, changed_notice):
    response = ask(local, "변경공고에서 뭐 바뀌었어?")
    assert response["intent"] == "CHANGED_NOTICE" and response["actions"] == []
    assert response["product_state"] == changed_notice.model_dump(mode="json")


def test_revalidation_does_not_consume_unrelated_answer_payload(real_proposals, changed_notice):
    response = ask(real_proposals, "전체 변경 요건 재검증해줘", requirement_key="R2", user_input={"satisfies_requirement": True})
    assert response["actions"] == [] and "별도 작업" in response["answer"]


@pytest.mark.parametrize("message", ["재검증해줘", "전체 변경 요건 재검증해줘", "그 조건으로 재검증해줘"])
def test_revalidation_receipt_backend_stale_is_control_result(local, changed_notice, monkeypatch, message):
    first = ask(local, "뭐가 바뀌었어?")
    def stale(*args):
        raise QualificationJudgmentError("STALE_ACTION_CONTEXT", "기준이 바뀌었습니다.", status_code=409)
    monkeypatch.setattr(flow, "get_changed_notice", stale)
    response = ask(local, message, conversation_context=hints(first))
    assert response["reply_context"]["status"] == "STALE_CONTEXT" and response["actions"] == []


def test_changed_receipt_checks_baseline_and_current_and_keeps_confirm_separate(local, changed_notice):
    first = ask(local, "뭐가 바뀌었어?")
    assert first["reply_context"]["last_read_receipt"]["kind"] == "revalidation"
    assert first["actions"] == []
    assert "이전 지역 요건" in first["answer"] and "현재:" in first["answer"]
    followup = ask(local, "왜?", conversation_context=hints(first))
    assert followup["intent"] == "CHANGED_NOTICE" and followup["reply_context"]["status"] == "RESOLVED"
    for side in ("baseline", "current"):
        context = hints(first)
        context["last_read_receipt"]["provenance"][side]["analysis_run_id"] = str(uuid4())
        stale = ask(local, "그 조건으로 재검증해줘", conversation_context=context)
        assert stale["reply_context"]["status"] == "STALE_CONTEXT" and stale["actions"] == []


@pytest.mark.parametrize("value,operator,expected", [(None, None, None), (None, ">=", None), (0, None, "비교값: 0"), (100, ">=", "비교값: >= 100")])
def test_change_presentation_omits_missing_values_but_keeps_zero(local, changed_notice, value, operator, expected):
    requirement = changed_notice.changes[0].current
    requirement.value = value
    requirement.operator = operator
    response = ask(local, "뭐가 바뀌었어?", requirement_key="R1")
    assert "None" not in response["answer"]
    if expected is None:
        assert "비교값:" not in response["answer"]
    else:
        assert expected in response["answer"]
    assert response["product_state"]["changes"][0]["current"]["value"] == value


@pytest.mark.parametrize("message", ["어떤 회사정보로 판단했어?", "재검증 관련 프로필", "재검증 결과에 사용한 프로필"])
def test_profile_keeps_stored_snapshot_and_receipt(local, monkeypatch, message):
    from apps.api.app.copilot.contracts import JudgmentProfileResult
    snapshot = {"company_id": str(local.summary.provenance.company_id), "name": "PRIVATE_COMPANY"}
    profile = JudgmentProfileResult(provenance=local.summary.provenance, profile_snapshot=snapshot, profile_completeness={})
    monkeypatch.setattr(flow, "get_judgment_profile_snapshot", lambda *args: profile.model_copy(deep=True))
    response = ask(local, message, intent="PROFILE_SNAPSHOT")
    assert response["intent"] == "PROFILE_SNAPSHOT"
    assert response["product_state"]["profile_snapshot"] == snapshot
    assert response["reply_context"]["last_read_receipt"]["provenance"] == local.summary.provenance.model_dump(mode="json")
    assert not response["external_processing_used"]


def test_public_document_path_keeps_optin_privacy_and_extractive_metadata(local, monkeypatch):
    from apps.api.app.copilot import document_qa as document_flow
    from bidengine.rag.answer import GroundedCitation, GroundedDocumentAnswer
    from bidengine.rag.store import VersionFaissIndex
    from apps.api.tests.test_document_rag_store import FakeEmbeddings, _record

    sent = []
    generated_questions = []

    class Embeddings(FakeEmbeddings):
        def embed_query(self, text):
            sent.append(text)
            return super().embed_query(text)

    embeddings = Embeddings()
    records = [_record(str(local.summary.provenance.notice_version_id), "c1", "공개 실적 조건"),
               _record(str(local.summary.provenance.notice_version_id), "c2", "공개 지역 조건")]
    for record in records:
        record.metadata.clause_label = "2"
        record.metadata.source_locations = ["p.2", "p.3"]
    index = VersionFaissIndex.build(records, embeddings=embeddings, embedding_model="fake")

    def fake_generate(question, hits, *args, **kwargs):
        generated_questions.append(question)
        citations = [GroundedCitation(
            ref=f"S{i}",
            document_id=hit.metadata.document_id,
            document_name=hit.metadata.document_name,
            notice_version_id=hit.metadata.notice_version_id,
            chunk_id=hit.metadata.chunk_id,
            clause_label=hit.metadata.clause_label,
            page=hit.metadata.page,
            source_locations=list(hit.metadata.source_locations),
            quote=hit.text,
        ) for i, hit in enumerate(hits, start=1)]
        refs = " ".join(f"[{citation.ref}]" for citation in citations)
        return GroundedDocumentAnswer(
            answer=f"공개 공고문에서 지역 조건 근거를 확인했습니다. {refs}",
            citations=citations,
            sources=citations,
        )

    monkeypatch.setattr(document_flow, "create_openai_embeddings", lambda: embeddings)
    monkeypatch.setattr(document_flow, "load_or_build_version_index", lambda *args, **kwargs: index)
    monkeypatch.setattr(document_flow, "generate_grounded_answer", fake_generate)

    private = "PRIVATE_MESSAGE_AND_USER_ANSWER"
    for extra in ({}, {"public_document_question": "지역 조건"}):
        response = ask(local, private, intent="DOCUMENT_QA", **extra)
        assert not response["external_processing_used"] and not sent

    response = ask(local, private, intent="DOCUMENT_QA", public_document_question="지역 조건", allow_external_processing=True,
                   user_input={"satisfies_requirement": False, "normalized_value": private})
    assert sent == ["지역 조건"]
    assert generated_questions == ["지역 조건"]
    assert response["sources"] == response["citations"] and len(response["sources"]) == 2
    assert all(source["source_locations"] == ["p.2", "p.3"] for source in response["sources"])
    assert private not in response["answer"] and private not in generated_questions
    assert response["product_state"] is None

    sent.clear()
    response = ask(local, "입찰 넣어도 돼?", intent="DOCUMENT_QA", public_document_question="지역 조건", allow_external_processing=True)
    assert response["intent"] == "QUALIFICATION_SUMMARY" and not sent
    assert generated_questions == ["지역 조건"]

    monkeypatch.setattr(document_flow, "retrieve", lambda *args, **kwargs: [])
    empty = ask(local, "공고문", public_document_question="지역 조건", allow_external_processing=True)
    assert "근거를 찾지 못했습니다" in empty["answer"]
    assert empty["sources"] == empty["citations"] == []
    assert generated_questions == ["지역 조건"]


@pytest.mark.parametrize("message", ["다음에 뭘 해야 해?", "무엇을 해야 해?", "뭐가 부족해?", "다음 할 일 알려줘"])
def test_next_steps_route_to_checks(local, message):
    response = ask(local, message)
    assert response["intent"] == "REQUIRED_CHECKS"
    assert response["presentation"]["reasons"] and response["presentation"]["next_action"]


@pytest.mark.parametrize("status,label", [("core_met", "핵심 요건 충족"), ("core_unmet", "핵심 요건 미충족")])
def test_presentation_never_replaces_backend_overall_status(local, status, label):
    local.summary.overall_status = status
    response = ask(local, "참여 가능해?")
    assert response["product_state"] == local.summary.model_dump(mode="json")
    assert label in response["presentation"]["conclusion"]
    assert not response["external_processing_used"]


def test_batch_adapter_preserves_metadata_with_one_validated_read(local, monkeypatch):
    from apps.api.app.copilot import product_tools
    calls = []
    def load(*args):
        calls.append(1)
        return local.summary.provenance, SimpleNamespace(requirements=local.requirements, evidence=[local.evidence]), None
    monkeypatch.setattr(product_tools, "_load_context", load)
    results = product_tools.get_explanation_evidence(local.db, local.summary.provenance.case_id, ["R2", "R1", "R2"])
    assert len(calls) == 1
    assert [r.requirement.requirement_key for r in results] == ["R2", "R1"]
    assert all(r.evidence == [local.evidence] for r in results)
    assert product_tools.matching_provenance(*results)
    with pytest.raises(QualificationJudgmentError, match="요건"):
        product_tools.get_explanation_evidence(local.db, local.summary.provenance.case_id, ["other-version-key"])
