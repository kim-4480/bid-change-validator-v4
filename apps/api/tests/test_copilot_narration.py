from types import SimpleNamespace
from uuid import uuid4

from bidengine.contracts import Evidence
from apps.api.app.copilot.chat import CopilotChatRequest, CopilotChatResponse, ProductSource
from apps.api.app.copilot.contracts import (
    AnalysisScope,
    JudgmentProfileResult,
    ProductProvenance,
    QualificationSummary,
    RequirementJudgmentSummary,
)
from apps.api.app.copilot.narration import apply_product_narration
from apps.api.app.copilot.presentation import Presentation, Reason, render_answer
from apps.api.app.copilot.source_map import SourceMap, cited_sources, source_identity
from bidengine.judgment.rules import ProfileCompleteness


def _fixture():
    provenance = ProductProvenance(
        case_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4(), version_number=2,
        company_id=uuid4(), analysis_run_id=uuid4(), judgment_run_id=uuid4(),
        analysis_status="PARTIAL", rule_version="test-rule",
    )
    judgments = [
        RequirementJudgmentSummary(
            judgment_key="J1", preflight_case_id=str(provenance.case_id),
            notice_version_id=str(provenance.notice_version_id), requirement_key="R1",
            status="UNSATISFIED", basis_type="PROFILE", reason_code="RULE_MISMATCH",
            requirement_evidence_keys=["E1"], type="INDUSTRY", raw="단체급식업 등록 필요",
        ),
        RequirementJudgmentSummary(
            judgment_key="J2", preflight_case_id=str(provenance.case_id),
            notice_version_id=str(provenance.notice_version_id), requirement_key="R2",
            status="SATISFIED", basis_type="PROFILE", reason_code="RULE_MATCH",
            requirement_evidence_keys=["E2"], type="INDUSTRY", raw="업종코드 1450 필요",
        ),
    ]
    summary = QualificationSummary(
        provenance=provenance, overall_status="core_unmet", analysis_status="PARTIAL",
        judgment_counts={"SATISFIED": 1, "UNSATISFIED": 1, "UNKNOWN": 0},
        judgments=judgments, analysis_scope=AnalysisScope(analysis_run_id=provenance.analysis_run_id),
    )
    evidence = Evidence(
        evidence_key="E1", source_type="NOTICE_DOCUMENT", document_id=str(uuid4()),
        notice_version_id=str(provenance.notice_version_id), chunk_id="c1",
        location={"page": 2, "clause_label": "나"}, quote="단체급식업 등록 필요",
        source_sha256="a" * 64, extracted_text_sha256="b" * 64,
    )
    source = ProductSource(ref="", evidence=evidence)
    mapping = SourceMap()
    identity = mapping.add(source)
    presentation = Presentation(
        conclusion="현재 저장된 판정은 핵심 요건 미충족입니다.",
        reasons=[Reason(text="업종 — 단체급식업 등록 필요", requirement_key="R1", evidence_refs=[identity])],
        limitations=["분석이 부분 완료 상태입니다."],
    )
    sources = mapping.finalize(presentation)
    answer = render_answer(presentation, sources)
    result = CopilotChatResponse(
        intent="QUALIFICATION_SUMMARY", answer=answer, product_state=summary,
        presentation=presentation, sources=sources,
        citations=cited_sources(answer, presentation, sources),
    )
    profile = JudgmentProfileResult(
        provenance=provenance,
        profile_snapshot={
            "company_id": str(provenance.company_id),
            "region_code": "11", "region_name": "서울특별시", "company_size": "SME",
            "industries": [{"code": "1450", "name": "구내식당업", "verified": True}],
            "staff": {"total_count": 8, "verified": True, "roles": []},
            "performances": [], "certifications": [],
            "completeness": ProfileCompleteness().model_dump(mode="json"),
        },
        profile_completeness=ProfileCompleteness(),
    )
    return provenance, summary, profile, result


def test_narrator_compacts_product_truth_without_changing_product_state(monkeypatch):
    _, summary, profile, result = _fixture()
    original_state = result.product_state.model_dump(mode="json")
    monkeypatch.setattr("apps.api.app.copilot.narration.get_judgment_profile_snapshot", lambda *args: profile)

    sent = {}
    def extractor(system, body, schema):
        sent["body"] = body
        assert schema["schema"]["properties"]["status"]["enum"] == ["core_unmet"]
        return {
            "status": "core_unmet",
            "conclusion": "현재는 핵심 요건 미충족으로 판정됐어요. 법적 참가 불가능을 확정하지 않습니다.",
            "points": [{"requirement_key": "R1", "text": "단체급식업 등록 조건을 충족하지 못했습니다."}],
            "caveat": "현재 분석은 일부 항목이 자동 판정 범위에 포함되지 않은 PARTIAL 상태입니다.",
            "next_action": "필요하면 미달 요건의 원문 근거를 확인해 보세요.",
        }

    request = CopilotChatRequest(case_id=summary.provenance.case_id, message="왜?")
    narrated = apply_product_narration(SimpleNamespace(), request, result, extractor=extractor)

    assert narrated.product_state.model_dump(mode="json") == original_state
    assert narrated.presentation.conclusion == "현재는 핵심 요건 미충족으로 판정됐어요. 법적 참가 불가능을 확정하지 않습니다."
    assert [reason.requirement_key for reason in narrated.presentation.reasons] == ["R1"]
    assert "R2" not in narrated.answer
    assert narrated.sources and narrated.citations == narrated.sources
    assert "company_id" not in sent["body"]
    assert "서울특별시" in sent["body"]


def test_narrator_cannot_flip_product_status(monkeypatch):
    _, summary, profile, result = _fixture()
    before = result.model_dump(mode="json")
    monkeypatch.setattr("apps.api.app.copilot.narration.get_judgment_profile_snapshot", lambda *args: profile)

    def extractor(*args):
        return {
            "status": "core_met",
            "conclusion": "참가 가능합니다.",
            "points": [], "caveat": None, "next_action": None,
        }

    request = CopilotChatRequest(case_id=summary.provenance.case_id, message="우리 회사 참여 가능해?")
    narrated = apply_product_narration(SimpleNamespace(), request, result, extractor=extractor)
    assert narrated.model_dump(mode="json") == before


def test_narrator_unknown_requirement_falls_back(monkeypatch):
    _, summary, profile, result = _fixture()
    before = result.model_dump(mode="json")
    monkeypatch.setattr("apps.api.app.copilot.narration.get_judgment_profile_snapshot", lambda *args: profile)

    def extractor(*args):
        return {
            "status": "core_unmet",
            "conclusion": "핵심 요건 미충족입니다.",
            "points": [{"requirement_key": "R999", "text": "없는 요건"}],
            "caveat": None, "next_action": None,
        }

    request = CopilotChatRequest(case_id=summary.provenance.case_id, message="왜?")
    narrated = apply_product_narration(SimpleNamespace(), request, result, extractor=extractor)
    assert narrated.model_dump(mode="json") == before


def test_narrator_provider_failure_falls_back(monkeypatch):
    _, summary, profile, result = _fixture()
    before = result.model_dump(mode="json")
    monkeypatch.setattr("apps.api.app.copilot.narration.get_judgment_profile_snapshot", lambda *args: profile)

    def extractor(*args):
        raise RuntimeError("provider unavailable")

    request = CopilotChatRequest(case_id=summary.provenance.case_id, message="왜?")
    narrated = apply_product_narration(SimpleNamespace(), request, result, extractor=extractor)
    assert narrated.model_dump(mode="json") == before
