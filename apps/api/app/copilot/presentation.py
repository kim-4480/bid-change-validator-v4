"""Explain stored facts without creating new eligibility decisions."""

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import JudgmentProfileResult, QualificationSummary, RequiredChecksResult, RequirementEvidenceResult
from .source_map import display_text, invalid_mapping, source_identity


class Reason(BaseModel):
    text: str
    requirement_key: str | None = None
    reason_code: str | None = None
    basis_type: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class NextAction(BaseModel):
    kind: Literal["SELECT_REQUIREMENT", "VIEW_EVIDENCE", "ANSWER_REQUIREMENT", "REVIEW_PROPOSAL", "REFRESH_RESULT"]
    label: str
    requirement_key: str | None = None


class Presentation(BaseModel):
    conclusion: str
    reasons: list[Reason] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    next_action: NextAction | None = None


TYPE_LABELS = {
    "PERFORMANCE_AMOUNT": "실적 금액", "PERFORMANCE_COUNT": "실적 건수", "INDUSTRY": "업종",
    "REGION": "지역", "STAFF": "인력", "REGISTRATION_CERTIFICATION": "등록·인증",
    "EXPERIENCE_FIELD": "수행 분야", "COMPANY_SIZE": "기업 규모",
}
REASON_LABELS = {
    "RULE_MATCH": "저장된 판정에서 이 조건을 충족했습니다.",
    "RULE_MISMATCH": "저장된 판정에서 이 조건을 충족하지 못했습니다.",
    "INSUFFICIENT_DATA": "판정에 필요한 정보가 충분하지 않습니다. 부족한 세부 정보는 원문과 함께 확인해 주세요.",
    "NEEDS_REVIEW": "이 조건은 추가 검토가 필요합니다.",
    "UNSUPPORTED_REQUIREMENT": "이 조건은 현재 자동 판정이 지원되지 않습니다.",
}
STATUS_CONCLUSIONS = {
    "eligible": "현재 저장된 판정은 참가 가능입니다.",
    "ineligible": "현재 저장된 판정은 참가 불가입니다.",
    "insufficient_data": "현재 저장된 판정만으로는 참가 가능 여부를 확정할 수 없습니다.",
}


def present_product(state, evidence_refs, focus=None, summary=None):
    presentation = Presentation(conclusion="현재 저장된 검토 결과입니다.")
    if isinstance(state, QualificationSummary):
        presentation.conclusion = STATUS_CONCLUSIONS[state.overall_status]
        items = [j for j in state.judgments if not focus or j.requirement_key == focus]
        for item in items:
            presentation.reasons.append(Reason(
                text=f"{TYPE_LABELS[item.type]} — {item.raw}\n{REASON_LABELS[item.reason_code]}",
                requirement_key=item.requirement_key, reason_code=item.reason_code, basis_type=item.basis_type,
                evidence_refs=evidence_refs.get(item.requirement_key, []),
            ))
        presentation.next_action = NextAction(kind="SELECT_REQUIREMENT", label="확인할 요건을 선택해 근거와 다음 할 일을 확인해 주세요.")
    elif isinstance(state, RequiredChecksResult):
        items = [q for q in state.questions if not focus or q.requirement_key == focus]
        if summary:
            status = STATUS_CONCLUSIONS[summary.overall_status]
            presentation.conclusion = (
                f"{status} 먼저 확인할 항목은 {len(items)}건입니다."
                if items else f"{status} 현재 추가로 답변할 확인 항목은 없습니다."
            )
        else:
            presentation.conclusion = (f"저장된 판정의 확인 대상 {len(items)}건입니다." if items
                                       else "선택한 범위에 사용자 확인 질문이 없습니다.")
        judgments = {j.requirement_key: j for j in summary.judgments} if summary else {}
        for question in items:
            judgment = judgments.get(question.requirement_key)
            text = question.question
            if judgment:
                text += "\n" + REASON_LABELS[judgment.reason_code]
            if question.askability_reason:
                text += "\n" + question.askability_reason
            text += ("\n이 요건은 답변을 입력하고 반영 내용을 확인할 수 있습니다." if question.askable
                     else "\n사용자 답변 적용 대상이 아닙니다. 관련 원문을 직접 검토해 주세요.")
            presentation.reasons.append(Reason(
                text=text, requirement_key=question.requirement_key,
                reason_code=judgment.reason_code if judgment else None,
                basis_type=judgment.basis_type if judgment else None,
                evidence_refs=evidence_refs.get(question.requirement_key, []),
            ))
        if len(items) == 1:
            question = items[0]
            presentation.next_action = NextAction(
                kind="ANSWER_REQUIREMENT" if question.askable else "VIEW_EVIDENCE",
                label="요건에 대한 답변을 입력해 주세요." if question.askable else "요건의 원문 근거를 확인해 주세요.",
                requirement_key=question.requirement_key,
            )
        elif items:
            presentation.next_action = NextAction(kind="SELECT_REQUIREMENT", label="먼저 확인할 요건을 선택해 주세요.")
    elif isinstance(state, RequirementEvidenceResult):
        presentation.conclusion = "선택한 요건에 연결된 공고문 원문입니다."
        presentation.reasons = [Reason(text=state.requirement.raw, requirement_key=state.requirement.requirement_key,
                                      evidence_refs=evidence_refs.get(state.requirement.requirement_key, []))]
        if not state.evidence:
            presentation.limitations.append("이 요건에 연결된 원문 근거가 없습니다.")
    elif isinstance(state, JudgmentProfileResult):
        presentation.conclusion = "이 판정에 사용한 당시 회사정보입니다."
        presentation.limitations.append("판정 당시 저장된 스냅샷이며, 현재 회사 프로필과 다를 수 있습니다.")
    else:
        # ChangedNoticeResult already contains canonical baseline/current requirements.
        presentation.conclusion = f"공고 {state.provenance.baseline.version_number}차와 {state.provenance.current.version_number}차의 분석된 요건을 비교했습니다."
        labels = {"ADDED": "추가", "REMOVED": "삭제", "MODIFIED": "변경", "UNCHANGED": "변경 없음"}
        for change in state.changes:
            key = change.current_key or change.baseline_key
            if focus and focus != key:
                continue
            parts = [labels[change.change_type]]
            for label, requirement in (("이전", change.baseline), ("현재", change.current)):
                if requirement:
                    text = f"{label}: {requirement.raw}"
                    if requirement.value is not None:
                        comparison = " ".join(str(value) for value in (requirement.operator, requirement.value) if value is not None)
                        text += f" (비교값: {comparison}; 단위: {requirement.unit or '미기재'})"
                    parts.append(text)
            presentation.reasons.append(Reason(text="\n".join(parts), requirement_key=key))
        presentation.limitations.append("분석된 요건의 비교이며, 공고 전체의 모든 변경을 확인했다는 의미는 아닙니다.")
    statuses = ([state.provenance.analysis_status] if hasattr(state.provenance, "analysis_status")
                else [state.provenance.baseline.analysis_status, state.provenance.current.analysis_status])
    if "PARTIAL" in statuses:
        presentation.limitations.append("분석이 부분 완료 상태여서 검토 범위에 한계가 있습니다. 이 상태만으로 구체적인 원인은 알 수 없습니다.")
    return presentation


def attach_analysis_scope(presentation, summary, sources):
    """Explain omitted scope without changing Product Truth or write targets."""
    scope = summary.analysis_scope if summary else None
    if scope is None:
        return
    if scope.analysis_run_id != summary.provenance.analysis_run_id:
        raise invalid_mapping()
    count = len(scope.notice_facts) + len(scope.dropped_requirements)
    if count:
        presentation.limitations.append(
            f"이 판정에 포함되지 않은 확인사항이 {count}건 있습니다. 참가자격 화면에서 함께 확인해 주세요."
        )
    for item in scope.notice_facts:
        refs = []
        for evidence in item.evidence:
            if evidence.notice_version_id != str(summary.provenance.notice_version_id):
                raise invalid_mapping()
            # Local import avoids the existing chat/presentation dependency cycle.
            from .chat import ProductSource
            source = ProductSource(ref="", evidence=evidence)
            sources.append(source)
            refs.append(source_identity(source))
        presentation.reasons.append(Reason(
            text="판정 대상이 아닌 확인사항 — " + item.message, evidence_refs=refs,
        ))
    labels = {
        "MISSING_RAW": "원문 문구가 없어 구조화에서 제외되었습니다.",
        "RAW_NOT_FOUND_IN_SOURCE": "제시된 문구를 원문에서 확인하지 못했습니다.",
        "DETAIL_NOT_FOUND_IN_SOURCE": "세부 조건을 원문에서 확인하지 못했습니다.",
        "SOURCE_VALIDATION_FAILED": "원문 대조를 통과하지 못했습니다.",
    }
    for item in scope.dropped_requirements:
        raw = item.raw.strip() or "원문 문구를 확보하지 못했습니다."
        presentation.reasons.append(Reason(
            text=f"구조화에서 제외된 요건 — {raw}\n{labels.get(item.reason_code, item.reason_code)}",
        ))
    if scope.pipeline_diagnostics:
        presentation.limitations.append(
            f"분석 처리 진단 {len(scope.pipeline_diagnostics)}건은 참가자격 화면의 분석 완전성에서 확인해 주세요."
        )


def render_answer(presentation, sources):
    lines = [display_text(presentation.conclusion)]
    for reason in presentation.reasons:
        refs = " ".join(f"[{ref}]" for ref in reason.evidence_refs)
        lines.append(f"{display_text(reason.text)} {refs}".rstrip())
    for source in sources:
        if source.source_origin == "PRODUCT_EVIDENCE":
            evidence = source.evidence
            location = evidence.location
            parts = []
            if location.clause_label:
                parts.append(f"조항 {location.clause_label}")
            if location.page is not None:
                parts.append(f"p.{location.page}")
            if location.section_index is not None:
                parts.append(f"section {location.section_index}")
            if location.paragraph_start is not None:
                parts.append(f"paragraph {location.paragraph_start}–{location.paragraph_end or location.paragraph_start}")
            if location.source_line_start is not None:
                parts.append(f"line {location.source_line_start}–{location.source_line_end if location.source_line_end is not None else location.source_line_start}")
            if location.block_start is not None:
                parts.append(f"block {location.block_start}–{location.block_end if location.block_end is not None else location.block_start}")
            if location.display:
                parts.append(location.display)
            locator = ", ".join(parts) or "위치 정보 없음"
            lines.append(f"[{source.ref}] {display_text(locator)} · {display_text(evidence.quote)}")
        else:
            location = ", ".join(source.source_locations) or (f"p.{source.page}" if source.page is not None else "위치 정보 없음")
            lines.append(f"[{source.ref}] {display_text(source.document_name)}; clause={display_text(source.clause_label or '정보 없음')}; location={display_text(location)}")
    lines.extend(display_text(text) for text in presentation.limitations)
    if presentation.next_action:
        lines.append(display_text(presentation.next_action.label))
    return "\n\n".join(lines)
