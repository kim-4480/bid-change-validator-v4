"""New baseline + Copilot presentation boundary; fake reads, no model/network."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from bidengine.pipeline.analysis_result import AnalysisDiagnostic, DroppedRequirement
from apps.api.app.config import get_settings
from apps.api.app.copilot.contracts import ActionInput, AnalysisNoticeFact, AnalysisScope, AnswerProposal
from apps.api.app.copilot.product_tools import analysis_scope
from apps.api.tests.test_copilot_chat_contract import local, ask, hints


def with_scope(local):
    local.summary.analysis_scope = AnalysisScope(
        analysis_run_id=local.summary.provenance.analysis_run_id,
        notice_facts=[AnalysisNoticeFact(code="UNMAPPED_REQUIREMENT", message="판정 대상이 아닌 확인사항입니다.", evidence=[local.evidence])],
        dropped_requirements=[DroppedRequirement(raw="", reason_code="MISSING_RAW")],
        pipeline_diagnostics=[AnalysisDiagnostic(code="TEST_PIPELINE", message="분석 범위 안내")],
    )


def test_scope_keeps_truth_sources_and_ordinal_namespace(local):
    with_scope(local)
    result = ask(local, "우리 회사 참여 가능해?")
    assert result["product_state"]["overall_status"] == local.summary.overall_status
    assert result["reply_context"]["visible_requirement_keys"] == ["R1", "R2"]
    assert "판정에 포함되지 않은 확인사항이 2건" in result["answer"]
    assert "원문 문구를 확보하지 못했습니다" in result["answer"]
    assert len(result["sources"]) == 1  # same evidence used by the judgment and fact
    assert result["citations"] == result["sources"]
    extras = [r for r in result["presentation"]["reasons"] if not r["requirement_key"]]
    assert len(extras) == 2 and extras[0]["evidence_refs"] == ["S1"]
    assert extras[1]["evidence_refs"] == []
    failed = ask(local, "세 번째 적용해줘", conversation_context=hints(result), user_input={"satisfies_requirement": True, "evidence_held": True})
    assert not failed["actions"] and not local.proposals


@pytest.mark.parametrize("message", ["판정 밖 두 번째 적용해줘", "구조화에서 제외된 요건 반영해줘", "NOTICE_FACT 두 번째 적용해줘", "공고 확인사항 재검증해줘"])
def test_scope_items_never_fall_back_to_qualification_target(local, message):
    with_scope(local)
    first = ask(local, "참여 가능해?")
    result = ask(local, message, requirement_key="R2", conversation_context=hints(first), user_input={"satisfies_requirement": True, "evidence_held": False})
    assert not result["actions"] and not local.proposals
    assert "답변 반영 대상이 아닙니다" in result["answer"]


def test_scope_preserves_missing_evidence_and_does_not_export_diagnostic_details(local):
    analysis = SimpleNamespace(id=local.summary.provenance.analysis_run_id, evidence=[local.evidence], dropped_requirements=[], diagnostics=[
        AnalysisDiagnostic(code="F", message="확인사항", kind="NOTICE_FACT", evidence_keys=["MISSING", "E1", "E1"]),
        AnalysisDiagnostic(code="P", message="처리 진단", details={"private_notes": "not part of explanation"}, evidence_keys=["MISSING"]),
    ])
    result = analysis_scope(analysis)
    assert [e.evidence_key for e in result.notice_facts[0].evidence] == ["E1"]
    assert result.pipeline_diagnostics[0].details == {}
    assert result.pipeline_diagnostics[0].evidence_keys == []
    assert analysis.diagnostics[1].details  # original persisted data untouched


def test_mismatched_analysis_scope_fails_closed(local):
    with_scope(local)
    local.summary.analysis_scope.analysis_run_id = uuid4()
    response = local.api.post('/api/v1/copilot/chat', json={"case_id": str(local.summary.provenance.case_id), "message": "참여 가능해?"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "COPILOT_SOURCE_MAPPING_INVALID"


@pytest.mark.parametrize("endpoint", ["chat", "actions/confirm"])
def test_existing_auth_dependency_protects_copilot_before_tools(local, monkeypatch, endpoint):
    monkeypatch.setattr(get_settings(), "auth_required", True)
    proposal = AnswerProposal(expected=local.summary.provenance, requirement_key="R2", user_input=ActionInput(satisfies_requirement=True))
    payload = ({"case_id": str(local.summary.provenance.case_id), "message": "참여 가능해?"} if endpoint == "chat" else {"confirmed": True, "action": proposal.model_dump(mode="json")})
    result = local.api.post('/api/v1/copilot/' + endpoint, json=payload)
    assert result.status_code == 401 and result.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert not local.calls and not local.proposals
