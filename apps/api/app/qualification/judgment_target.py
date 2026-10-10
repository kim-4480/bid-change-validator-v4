"""Allow one preflight case to create judgments for its baseline or current analysis run.

The original Stage 5 service defaults to the current version. Changed-notice E2E
also needs a baseline JudgmentRun on the same case so Ask-back can complete before
Stage 7 revalidation. This adapter preserves the default behavior while allowing
an explicit analysis_run_id that belongs to either case version.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from bidengine.judgment.rules import RULE_VERSION, judge_requirements
from .analysis import no_restriction_stated
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import CompanyQualificationProfileCompleteness, QualificationJudgmentRecord, QualificationJudgmentRun
from .analysis import analysis_run_response, is_qualification_analysis_run_stale
from .judgment import (
    load_judgment_analysis,
    QualificationJudgmentError,
    _load_case,
    _load_company,
    _record_to_completeness,
    build_company_profile_snapshot,
    grounded_keys_for_analysis,
    load_qualification_judgment_run,
    run_qualification_judgment,
)


def run_targeted_qualification_judgment(
    db: Session,
    *,
    case_id: UUID,
    analysis_run_id: UUID | None = None,
    reference_date: date | None = None,
) -> QualificationJudgmentRun:
    if analysis_run_id is None:
        return run_qualification_judgment(
            db,
            case_id=case_id,
            reference_date=reference_date,
        )

    case = _load_case(db, case_id)
    if case.company_id is None:
        raise QualificationJudgmentError(
            "COMPANY_PROFILE_REQUIRED",
            "자격 판정을 위해 사전검토 건에 회사 프로필이 필요합니다.",
            status_code=422,
        )
    analysis_run = load_judgment_analysis(db, analysis_run_id)
    allowed_versions = {case.current_version_id}
    if case.baseline_version_id is not None:
        allowed_versions.add(case.baseline_version_id)
    if analysis_run.notice_version_id not in allowed_versions:
        raise QualificationJudgmentError(
            "ANALYSIS_VERSION_MISMATCH",
            "선택한 분석 결과는 이 사전검토 건의 baseline/current 공고 버전에 속하지 않습니다.",
            status_code=422,
        )
    if analysis_run.status == "FAILED":
        raise QualificationJudgmentError(
            "QUALIFICATION_ANALYSIS_FAILED",
            "실패한 자격요건 분석 결과로는 판정할 수 없습니다.",
        )
    if is_qualification_analysis_run_stale(analysis_run):
        raise QualificationJudgmentError(
            "QUALIFICATION_ANALYSIS_STALE",
            "문서가 재추출되어 자격요건을 다시 분석해야 합니다.",
        )

    company = _load_company(db, case.company_id)
    completeness = _record_to_completeness(
        db.get(CompanyQualificationProfileCompleteness, company.id)
    )
    profile = build_company_profile_snapshot(company, completeness)
    analysis = analysis_run_response(analysis_run)
    actual_reference_date = reference_date or date.today()
    evaluation = judge_requirements(
        analysis.requirements,
        profile,
        preflight_case_id=str(case.id),
        reference_date=actual_reference_date,
        analysis_status=analysis_run.status,
        coverage_complete=analysis.verdict_complete, no_restriction_stated=no_restriction_stated(analysis),
        grounded_requirement_keys=grounded_keys_for_analysis(analysis_run, analysis),
    )
    overall_status = evaluation.overall_status

    run = QualificationJudgmentRun(
        preflight_case_id=case.id,
        analysis_run_id=analysis_run.id,
        company_id=case.company_id,
        notice_version_id=analysis_run.notice_version_id,
        overall_status=overall_status,
        rule_version=RULE_VERSION,
        reference_date=actual_reference_date,
        profile_snapshot=profile.model_dump(mode="json"),
        analysis_status=analysis_run.status,
    )
    db.add(run)
    db.flush()
    for item in evaluation.judgments:
        db.add(
            QualificationJudgmentRecord(
                judgment_run_id=run.id,
                judgment_key=item.judgment_key,
                requirement_key=item.requirement_key,
                status=item.status,
                basis_type=item.basis_type,
                evidence_held=item.evidence_held,
                value_source=item.value_source,
                evidence_status=item.evidence_status,
                reason_code=item.reason_code,
                unknown_reason=item.unknown_reason,
                requires_evidence=item.requires_evidence,
                profile_refs=list(item.profile_refs),
                requirement_evidence_keys=list(item.requirement_evidence_keys),
                rule_version=item.rule_version,
            )
        )
    db.commit()
    return load_qualification_judgment_run(db, run.id)
