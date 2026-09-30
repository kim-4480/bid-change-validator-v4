from types import SimpleNamespace
from uuid import uuid4

from bidengine.contracts import Evidence
from apps.api.app.ask_back_schemas import QualificationQuestionRead
from apps.api.app.copilot.chat import CopilotChatRequest, CopilotChatResponse
from apps.api.app.copilot.contracts import (
    AnalysisNoticeFact,
    AnalysisScope,
    JudgmentProfileResult,
    ProductProvenance,
    QualificationSummary,
    RequiredChecksResult,
    RequirementJudgmentSummary,
)
from apps.api.app.copilot.narration import apply_product_narration
from apps.api.app.copilot.presentation import Presentation, Reason
from bidengine.judgment.rules import ProfileCompleteness


def _fixture(*, with_question: bool = False):
    provenance = ProductProvenance(
        case_id=uuid4(), notice_id=uuid4(), notice_version_id=uuid4(), version_number=2,
        company_id=uuid4(), analysis_run_id=uuid4(), judgment_run_id=uuid4(),
        analysis_status="SUCCEEDED", rule_version="test-rule",
    )
    evidence = Evidence(
        evidence_key="E-MANUAL", source_type="NOTICE_DOCUMENT", document_id=str(uuid4()),
        notice_version_id=str(provenance.notice_version_id), chunk_id="manual-1",
        location={"clause_label": "가", "paragraph_start": 30},
        quote="국가계약법 시행령 제12조 및 시행규칙 제14조에 따른 자격을 갖춘 업체",
    )
    summary = QualificationSummary(
        provenance=provenance,
        overall_status="ineligible",
        analysis_status="SUCCEEDED",
        judgment_counts={"SATISFIED": 1, "UNSATISFIED": 1, "UNKNOWN": 0},
        judgments=[
            RequirementJudgmentSummary(
                judgment_key="J1", preflight_case_id=str(provenance.case_id),
                notice_version_id=str(provenance.notice_version_id), requirement_key="R1",
                status="UNSATISFIED", basis_type="PROFILE", reason_code="RULE_MISMATCH",
                requirement_evidence_keys=[], type="INDUSTRY", raw="단체급식업 등록 필요",
            ),
            RequirementJudgmentSummary(
                judgment_key="J2", preflight_case_id=str(provenance.case_id),
                notice_version_id=str(provenance.notice_version_id), requirement_key="R2",
                status="SATISFIED", basis_type="PROFILE", reason_code="RULE_MATCH",
                requirement_evidence_keys=[], type="INDUSTRY", raw="업종코드 1450 필요",
            ),
        ],
        analysis_scope=AnalysisScope(
            analysis_run_id=provenance.analysis_run_id,
            notice_facts=[
                AnalysisNoticeFact(
                    code="NOTICE_FACT",
                    message="공고에서 확인했으나 회사 프로필과 자동 대조할 자격요건이 아닙니다.",
                    evidence=[evidence],
                )
            ],
        ),
    )
    questions = []
    if with_question:
        questions = [
            QualificationQuestionRead(
                requirement_key="R1", requirement_type="INDUSTRY",
                question="단체급식업 등록 여부를 확인해 주세요.", raw_requirement="단체급식업 등록 필요",
                askable=True,
            )
        ]
    checks = RequiredChecksResult(provenance=provenance, questions=questions)
    result = CopilotChatResponse(
        intent="REQUIRED_CHECKS",
        answer="legacy long answer",
        product_state=checks,
        presentation=Presentation(
            conclusion="현재 저장된 판정은 참가 불가입니다. 현재 추가로 답변할 확인 항목은 없습니다.",
            reasons=[Reason(text=f"판정 대상이 아닌 확인사항 {i}") for i in range(9)],
            limitations=["이 판정에 포함되지 않은 확인사항이 9건 있습니다."],
        ),
        sources=[], citations=[],
    )
    profile = JudgmentProfileResult(
        provenance=provenance,
        profile_snapshot={
            "company_id": str(provenance.company_id),
            "region_name": "서울특별시", "company_size": "SME",
            "industries": [], "staff": None, "performances": [], "certifications": [],
            "completeness": ProfileCompleteness().model_dump(mode="json"),
        },
        profile_completeness=ProfileCompleteness(),
    )
    return summary, checks, profile, result


def test_required_checks_provider_failure_keeps_compact_manual_review_fallback(monkeypatch):
    summary, _, profile, result = _fixture()
    monkeypatch.setattr("apps.api.app.copilot.narration.get_qualification_summary", lambda *args: summary)
    monkeypatch.setattr("apps.api.app.copilot.narration.get_judgment_profile_snapshot", lambda *args: profile)

    def extractor(*args):
        raise RuntimeError("provider unavailable")

    request = CopilotChatRequest(case_id=summary.provenance.case_id, message="뭘 더 확인해야 해?")
    narrated = apply_product_narration(SimpleNamespace(), request, result, extractor=extractor)

    assert "추가로 입력해 판정을 갱신할 회사정보는 없습니다" in narrated.answer
    assert "직접 확인해야 할 항목이 1건" in narrated.answer
    assert "판정 대상이 아닌 확인사항 0" not in narrated.answer
    assert len(narrated.presentation.reasons) == 0
    assert narrated.sources == narrated.citations == []


def test_required_checks_narrator_receives_actual_manual_review_evidence(monkeypatch):
    summary, _, profile, result = _fixture()
    monkeypatch.setattr("apps.api.app.copilot.narration.get_qualification_summary", lambda *args: summary)
    monkeypatch.setattr("apps.api.app.copilot.narration.get_judgment_profile_snapshot", lambda *args: profile)

    sent = {}
    def extractor(_system, body, _schema):
        sent["body"] = body
        return {
            "status": "ineligible",
            "conclusion": "추가로 입력할 회사정보는 없지만 공고에서 직접 확인할 항목이 있습니다.",
            "points": [
                {"requirement_key": None, "text": "국가계약법상 기본 참가자격을 원문에서 확인해 주세요."}
            ],
            "caveat": None,
            "next_action": "참가자격 화면에서 해당 원문을 확인해 보세요.",
        }

    request = CopilotChatRequest(case_id=summary.provenance.case_id, message="뭘 더 확인해야 해?")
    narrated = apply_product_narration(SimpleNamespace(), request, result, extractor=extractor)

    assert "국가계약법 시행령 제12조" in sent["body"]
    assert "manual_review_count\": 1" in sent["body"]
    assert narrated.presentation.reasons[0].requirement_key is None
    assert "직접 확인" in narrated.answer


def test_required_checks_with_answerable_question_keeps_question_target_on_fallback(monkeypatch):
    summary, _, profile, result = _fixture(with_question=True)
    result.presentation.reasons = [
        Reason(text="단체급식업 등록 여부를 확인해 주세요.", requirement_key="R1")
    ]
    monkeypatch.setattr("apps.api.app.copilot.narration.get_qualification_summary", lambda *args: summary)
    monkeypatch.setattr("apps.api.app.copilot.narration.get_judgment_profile_snapshot", lambda *args: profile)

    def extractor(*args):
        raise RuntimeError("provider unavailable")

    request = CopilotChatRequest(case_id=summary.provenance.case_id, message="뭘 더 확인해야 해?")
    narrated = apply_product_narration(SimpleNamespace(), request, result, extractor=extractor)

    assert "회사정보는 1건" in narrated.answer
    assert [reason.requirement_key for reason in narrated.presentation.reasons] == ["R1"]
