"""Generate safe ask-back questions and partially re-judge one UNKNOWN requirement."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from bidengine.judgment.askability import build_semantic_question, classify_askability
from bidengine.contracts import Judgment
from bidengine.judgment.rules import RULE_VERSION, derive_overall_status
from ..models import PreflightCase
from ..ask_back_models import QualificationAnswer
from ..ask_back_schemas import QualificationAnswerCreate, QualificationAnswerRead, QualificationQuestionRead
from ..judgment_models import CompanyQualificationProfileCompleteness, QualificationJudgmentRecord, QualificationJudgmentRun
from .analysis import (
    analysis_run_response,
    is_qualification_analysis_run_stale,
    load_latest_current_qualification_analysis_run,
)
from .judgment import load_judgment_analysis, QualificationJudgmentError, judgment_run_response, load_qualification_judgment_run, _load_company, _record_to_completeness, build_company_profile_snapshot, grounded_keys_for_analysis


def list_questions(
    db: Session,
    *,
    case_id: UUID,
    source_judgment_run_id: UUID | None = None,
) -> list[QualificationQuestionRead]:
    if source_judgment_run_id is None:
        source_judgment_run_id = db.scalar(
            select(QualificationJudgmentRun.id)
            .where(QualificationJudgmentRun.preflight_case_id == case_id)
            .order_by(QualificationJudgmentRun.created_at.desc())
            .limit(1)
        )
        if source_judgment_run_id is None:
            raise QualificationJudgmentError(
                "JUDGMENT_RUN_REQUIRED", "먼저 자격 판정을 실행해야 합니다."
            )

    run = load_qualification_judgment_run(db, source_judgment_run_id)
    if run.preflight_case_id != case_id:
        raise QualificationJudgmentError(
            "JUDGMENT_CASE_MISMATCH",
            "판정 실행과 사전검토 건이 일치하지 않습니다.",
            status_code=422,
        )
    if run.rule_version != RULE_VERSION:
        raise QualificationJudgmentError("STALE_JUDGMENT", "새 핵심 요건 기준으로 다시 판정한 뒤 답변해 주세요.", status_code=409)

    analysis_record = load_judgment_analysis(db, run.analysis_run_id)
    if is_qualification_analysis_run_stale(analysis_record):
        raise QualificationJudgmentError(
            "STALE_JUDGMENT",
            "문서가 재추출되어 새 분석과 판정이 필요합니다.",
        )
    analysis = analysis_run_response(analysis_record)
    grounded = grounded_keys_for_analysis(analysis_record, analysis)
    req_by_key = {requirement.requirement_key: requirement for requirement in analysis.requirements}
    questions: list[QualificationQuestionRead] = []

    for item in run.judgments:
        if item.status != "UNKNOWN":
            continue
        requirement = req_by_key.get(item.requirement_key)
        if requirement is None:
            continue
        decision = classify_askability(requirement)
        verified = requirement.requirement_key in grounded
        questions.append(
            QualificationQuestionRead(
                requirement_key=requirement.requirement_key,
                requirement_type=requirement.type,
                question=(
                    build_semantic_question(requirement)
                    if decision.askable and verified
                    else "사용자 답변만으로 판정할 수 없는 조건입니다. 근거 원문을 직접 확인해 주세요."
                ),
                raw_requirement=requirement.raw,
                askable=decision.askable and verified,
                askability_reason_code=decision.reason_code if verified else "SOURCE_EVIDENCE_UNVERIFIED",
                askability_reason=decision.reason if verified else "공고 원문 근거가 확인되지 않아 답변으로 확정할 수 없습니다.",
            )
        )

    return sorted(questions, key=lambda question: question.requirement_key)


def answer_and_rejudge(
    db: Session,
    *,
    case_id: UUID,
    payload: QualificationAnswerCreate,
) -> QualificationAnswerRead:
    if payload.apply_to_profile:
        raise QualificationJudgmentError(
            "PROFILE_MUTATION_NOT_SUPPORTED",
            "MVP Ask-back에서는 답변 저장만 지원하며 프로필 자동 수정은 아직 지원하지 않습니다.",
            status_code=422,
        )

    # Serialize answers for a case so concurrent tabs cannot overwrite each other.
    case = db.scalar(select(PreflightCase).where(PreflightCase.id == case_id).with_for_update())
    if case is None:
        raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "사전검토 건을 찾을 수 없습니다.", status_code=404)
    source = load_qualification_judgment_run(db, payload.source_judgment_run_id)
    if source.preflight_case_id != case_id:
        raise QualificationJudgmentError(
            "JUDGMENT_CASE_MISMATCH",
            "판정 실행과 사전검토 건이 일치하지 않습니다.",
            status_code=422,
        )

    latest_id = db.scalar(select(QualificationJudgmentRun.id).where(QualificationJudgmentRun.preflight_case_id == case_id, QualificationJudgmentRun.notice_version_id == source.notice_version_id).order_by(QualificationJudgmentRun.created_at.desc()).limit(1))
    latest_analysis = load_latest_current_qualification_analysis_run(
        db, notice_version_id=source.notice_version_id, include_failed=True
    )
    latest_analysis_id = latest_analysis.id if latest_analysis is not None else None
    if source.id != latest_id or source.analysis_run_id != latest_analysis_id or source.rule_version != RULE_VERSION:
        raise QualificationJudgmentError("STALE_JUDGMENT", "분석 또는 판정이 갱신되었습니다. 새로 검토한 뒤 답변해 주세요.", status_code=409)
    if source.company_id != case.company_id or source.notice_version_id not in {case.baseline_version_id, case.current_version_id}:
        raise QualificationJudgmentError("JUDGMENT_CASE_MISMATCH", "판정의 회사 또는 공고 차수가 검토 건과 다릅니다.", status_code=422)
    company = _load_company(db, case.company_id)
    completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, company.id))
    if build_company_profile_snapshot(company, completeness).model_dump(mode="json") != dict(source.profile_snapshot):
        raise QualificationJudgmentError("PROFILE_CHANGED_FULL_REJUDGMENT_REQUIRED", "회사 프로필이 변경되었습니다. 전체 판정 후 답변해 주세요.", status_code=409)

    source_by_key = {judgment.requirement_key: judgment for judgment in source.judgments}
    original = source_by_key.get(payload.requirement_key)
    if original is None:
        raise QualificationJudgmentError(
            "REQUIREMENT_JUDGMENT_NOT_FOUND",
            "답변할 Requirement 판정을 찾을 수 없습니다.",
            status_code=404,
        )
    if original.status != "UNKNOWN":
        raise QualificationJudgmentError(
            "ANSWER_NOT_REQUIRED",
            "UNKNOWN 상태인 Requirement만 Ask-back 답변으로 재판정할 수 있습니다.",
            status_code=422,
        )

    analysis_record = load_judgment_analysis(db, source.analysis_run_id)
    analysis = analysis_run_response(analysis_record)
    requirement = next(
        (item for item in analysis.requirements if item.requirement_key == payload.requirement_key),
        None,
    )
    if requirement is None:
        raise QualificationJudgmentError(
            "REQUIREMENT_NOT_FOUND",
            "분석 결과에서 Requirement를 찾을 수 없습니다.",
            status_code=404,
        )
    if requirement.requirement_key not in grounded_keys_for_analysis(analysis_record, analysis):
        raise QualificationJudgmentError(
            "SOURCE_EVIDENCE_UNVERIFIED", "공고 원문 근거가 확인되지 않아 답변으로 확정할 수 없습니다.", status_code=422,
        )

    decision = classify_askability(requirement)
    if not decision.askable:
        raise QualificationJudgmentError(
            "REQUIREMENT_NOT_ASKABLE",
            f"이 조건은 사용자 답변만으로 재판정할 수 없습니다. ({decision.reason_code})",
            status_code=422,
        )

    replacement = Judgment(
        judgment_key=f"JUDG:{case_id}:{requirement.requirement_key}",
        preflight_case_id=str(case_id),
        notice_version_id=str(source.notice_version_id),
        requirement_key=requirement.requirement_key,
        status="SATISFIED" if payload.satisfies_requirement else "UNSATISFIED",
        basis_type="USER_ANSWER",
        evidence_held=payload.evidence_held,
        value_source="askback",
        evidence_status="declared" if payload.evidence_held else "none",
        reason_code="RULE_MATCH" if payload.satisfies_requirement else "RULE_MISMATCH",
        requires_evidence=original.requires_evidence,
        profile_refs=[],
        requirement_evidence_keys=list(original.requirement_evidence_keys or []),
        rule_version=source.rule_version,
    )

    judgments: list[Judgment] = []
    for item in source.judgments:
        if item.requirement_key == payload.requirement_key:
            judgments.append(replacement)
        else:
            judgments.append(
                Judgment(
                    judgment_key=item.judgment_key,
                    preflight_case_id=str(source.preflight_case_id),
                    notice_version_id=str(source.notice_version_id),
                    requirement_key=item.requirement_key,
                    status=item.status,
                    basis_type=item.basis_type,
                    evidence_held=item.evidence_held,
                    value_source=item.value_source,
                    evidence_status=item.evidence_status,
                    reason_code=item.reason_code,
                    unknown_reason=item.unknown_reason,
                    requires_evidence=item.requires_evidence,
                    profile_refs=list(item.profile_refs or []),
                    requirement_evidence_keys=list(item.requirement_evidence_keys or []),
                    rule_version=item.rule_version,
                )
            )

    overall = derive_overall_status(analysis.requirements, judgments, analysis_status=analysis.status, coverage_complete=analysis.verdict_complete)
    result_run = QualificationJudgmentRun(
        preflight_case_id=source.preflight_case_id,
        analysis_run_id=source.analysis_run_id,
        company_id=source.company_id,
        notice_version_id=source.notice_version_id,
        overall_status=overall,
        rule_version=source.rule_version,
        reference_date=source.reference_date,
        profile_snapshot=dict(source.profile_snapshot),
        analysis_status=source.analysis_status,
    )
    db.add(result_run)
    db.flush()

    for judgment in judgments:
        db.add(
            QualificationJudgmentRecord(
                judgment_run_id=result_run.id,
                judgment_key=judgment.judgment_key,
                requirement_key=judgment.requirement_key,
                status=judgment.status,
                basis_type=judgment.basis_type,
                evidence_held=judgment.evidence_held,
                value_source=judgment.value_source,
                evidence_status=judgment.evidence_status,
                reason_code=judgment.reason_code,
                unknown_reason=judgment.unknown_reason,
                requires_evidence=judgment.requires_evidence,
                profile_refs=list(judgment.profile_refs),
                requirement_evidence_keys=list(judgment.requirement_evidence_keys),
                rule_version=judgment.rule_version,
            )
        )

    answer = QualificationAnswer(
        preflight_case_id=case_id,
        source_judgment_run_id=source.id,
        result_judgment_run_id=result_run.id,
        requirement_key=requirement.requirement_key,
        answer_json={"satisfies_requirement": payload.satisfies_requirement},
        normalized_value=payload.normalized_value,
        evidence_held=payload.evidence_held,
        apply_to_profile=False,
    )
    db.add(answer)
    db.commit()
    db.refresh(answer)

    result = judgment_run_response(load_qualification_judgment_run(db, result_run.id))
    return QualificationAnswerRead(
        id=answer.id,
        preflight_case_id=answer.preflight_case_id,
        source_judgment_run_id=answer.source_judgment_run_id,
        result_judgment_run_id=result_run.id,
        requirement_key=answer.requirement_key,
        answer=dict(answer.answer_json),
        normalized_value=answer.normalized_value,
        evidence_held=answer.evidence_held,
        apply_to_profile=answer.apply_to_profile,
        created_at=answer.created_at,
        result=result,
    )
