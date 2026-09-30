"""Read persisted state only: no judging, extraction, vector search or writes.

Callers own the Session/transaction. no_autoflush also prevents these reads from
flushing unrelated pending caller changes. Results describe the observed state;
subsequent user actions must revalidate freshness at their own write boundary.
"""

from copy import deepcopy
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..analysis_models import QualificationAnalysisRun
from ..analysis_schemas import QualificationAnalysisRunRead
from ..judgment_schemas import QualificationJudgmentRunRead
from ..models import PreflightCase
from ..qualification.analysis import analysis_run_response, load_qualification_analysis_run
from ..qualification.ask_back import list_questions
from ..qualification.judgment import (
    QualificationJudgmentError,
    judgment_run_response,
    list_qualification_judgment_runs,
    load_qualification_judgment_run,
)
from bidengine.judgment.rules import RULE_VERSION
from .contracts import (
    AnalysisScope, AnalysisNoticeFact,
    JudgmentProfileResult,
    ProductProvenance,
    QualificationSummary,
    RequiredChecksResult,
    RequirementEvidenceResult,
    RequirementJudgmentSummary,
)


def _load_context(
    db: Session, case_id: UUID,
) -> tuple[ProductProvenance, QualificationAnalysisRunRead, QualificationJudgmentRunRead]:
    case = db.get(PreflightCase, case_id)
    if case is None:
        raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "사전검토 건을 찾을 수 없습니다.", status_code=404)

    latest_id = db.scalar(
        select(QualificationAnalysisRun.id)
        .where(QualificationAnalysisRun.notice_version_id == case.current_version_id)
        .order_by(QualificationAnalysisRun.created_at.desc(), QualificationAnalysisRun.id.desc())
        .limit(1)
    )
    if latest_id is None:
        raise QualificationJudgmentError("CURRENT_JUDGMENT_REQUIRED", "현재 공고 버전의 판정이 필요합니다.")

    analysis_run = load_qualification_analysis_run(db, latest_id)
    if analysis_run.notice_version_id != case.current_version_id or analysis_run.notice_version.notice_id != case.notice_id:
        raise QualificationJudgmentError("ANALYSIS_VERSION_MISMATCH", "현재 공고와 분석 버전이 다릅니다.")
    if analysis_run.status == "FAILED":
        raise QualificationJudgmentError("QUALIFICATION_ANALYSIS_FAILED", "실패한 분석의 판정은 반환할 수 없습니다.")

    runs = list_qualification_judgment_runs(db, case_id=case_id)
    current_candidates = [
        item for item in runs
        if item.notice_version_id == case.current_version_id and item.rule_version == RULE_VERSION
    ]
    if not current_candidates:
        raise QualificationJudgmentError(
            "CURRENT_JUDGMENT_REQUIRED",
            "현재 공고 버전과 판정 규칙으로 생성된 판정이 필요합니다.",
        )

    analysis_candidates = [item for item in current_candidates if item.analysis_run_id == latest_id]
    if not analysis_candidates:
        raise QualificationJudgmentError("STALE_JUDGMENT", "최신 분석을 사용한 판정이 필요합니다.")

    company_candidates = [item for item in analysis_candidates if item.company_id == case.company_id]
    if not company_candidates:
        raise QualificationJudgmentError("JUDGMENT_CASE_MISMATCH", "판정의 검토 건 또는 회사가 다릅니다.")

    selected = max(company_candidates, key=lambda item: (item.created_at, str(item.id)))
    run = load_qualification_judgment_run(db, selected.id)
    if run.notice_version_id != case.current_version_id:
        raise QualificationJudgmentError("JUDGMENT_VERSION_MISMATCH", "현재 버전과 판정 버전이 다릅니다.")
    if run.rule_version != RULE_VERSION:
        raise QualificationJudgmentError("CURRENT_JUDGMENT_REQUIRED", "현재 판정 규칙으로 생성된 판정이 필요합니다.")
    if run.preflight_case_id != case.id or run.company_id != case.company_id:
        raise QualificationJudgmentError("JUDGMENT_CASE_MISMATCH", "판정의 검토 건 또는 회사가 다릅니다.")
    if run.analysis_run_id != latest_id:
        raise QualificationJudgmentError("STALE_JUDGMENT", "최신 분석을 사용한 판정이 필요합니다.")
    if run.analysis_status != analysis_run.status:
        raise QualificationJudgmentError("ANALYSIS_STATUS_MISMATCH", "분석과 판정에 기록된 분석 상태가 다릅니다.")
    analysis = analysis_run_response(analysis_run)
    judgment = judgment_run_response(run)
    if judgment.profile_snapshot.get("company_id") != str(case.company_id):
        raise QualificationJudgmentError("JUDGMENT_CASE_MISMATCH", "판정 스냅샷의 회사가 다릅니다.")
    # Historical product reads describe the exact snapshot used by the persisted
    # judgment. They must not silently switch to current profile state. Freshness
    # is revalidated at write/action boundaries by the qualification services.
    judgment.profile_snapshot = deepcopy(run.profile_snapshot)
    requirement_keys = {item.requirement_key for item in analysis.requirements}
    if requirement_keys != {item.requirement_key for item in judgment.judgments}:
        raise QualificationJudgmentError("REQUIREMENT_JUDGMENT_MISMATCH", "요건과 판정 연결이 불완전합니다.")
    for evidence in analysis.evidence:
        if evidence.notice_version_id != str(case.current_version_id):
            raise QualificationJudgmentError("EVIDENCE_VERSION_MISMATCH", "근거의 공고 버전이 다릅니다.")
    evidence_keys = {item.evidence_key for item in analysis.evidence}
    referenced = {key for item in analysis.requirements for key in item.evidence_keys}
    referenced.update(key for item in judgment.judgments for key in item.requirement_evidence_keys)
    if not referenced <= evidence_keys:
        raise QualificationJudgmentError("EVIDENCE_NOT_FOUND", "분석에 저장된 참조 근거가 없습니다.")
    provenance = ProductProvenance(
        case_id=case.id, notice_id=case.notice_id, notice_version_id=case.current_version_id,
        version_number=analysis.version_number, company_id=run.company_id,
        analysis_run_id=analysis.id, judgment_run_id=run.id,
        analysis_status=analysis.status, rule_version=run.rule_version,
    )
    return provenance, analysis, judgment


def analysis_scope(analysis: QualificationAnalysisRunRead) -> AnalysisScope:
    evidence = {item.evidence_key: item for item in analysis.evidence}
    return AnalysisScope(
        analysis_run_id=analysis.id,
        notice_facts=[AnalysisNoticeFact(
            code=item.code, message=item.message,
            evidence=[evidence[key] for key in dict.fromkeys(item.evidence_keys) if key in evidence],
        ) for item in analysis.diagnostics if item.kind == "NOTICE_FACT"],
        dropped_requirements=[item.model_copy(deep=True) for item in analysis.dropped_requirements],
        pipeline_diagnostics=[item.model_copy(update={"details": {}, "evidence_keys": []})
                              for item in analysis.diagnostics if item.kind != "NOTICE_FACT"],
    )


def get_qualification_summary(db: Session, case_id: UUID) -> QualificationSummary:
    with db.no_autoflush:
        provenance, analysis, judgment = _load_context(db, case_id)
        requirements = {item.requirement_key: item for item in analysis.requirements}
        return QualificationSummary(
            provenance=provenance, overall_status=judgment.overall_status,
            analysis_status=provenance.analysis_status, analysis_scope=analysis_scope(analysis),
            judgment_counts={status: sum(item.status == status for item in judgment.judgments)
                             for status in ("SATISFIED", "UNSATISFIED", "UNKNOWN")},
            judgments=[RequirementJudgmentSummary(
                **item.model_dump(), type=requirements[item.requirement_key].type,
                raw=requirements[item.requirement_key].raw,
            ) for item in judgment.judgments],
        )


def get_requirement_evidence(db: Session, case_id: UUID, requirement_key: str) -> RequirementEvidenceResult:
    return get_explanation_evidence(db, case_id, [requirement_key])[0]


def get_explanation_evidence(db: Session, case_id: UUID, requirement_keys: list[str]) -> list[RequirementEvidenceResult]:
    with db.no_autoflush:
        provenance, analysis, _ = _load_context(db, case_id)
        requirements = {item.requirement_key: item for item in analysis.requirements}
        if not set(requirement_keys) <= requirements.keys():
            raise QualificationJudgmentError("REQUIREMENT_NOT_FOUND", "분석에서 요건을 찾을 수 없습니다.", status_code=404)
        evidence = {item.evidence_key: item for item in analysis.evidence}
        return [RequirementEvidenceResult(
            provenance=provenance, requirement=requirements[key],
            evidence=[evidence[ref] for ref in dict.fromkeys(requirements[key].evidence_keys)],
        ) for key in dict.fromkeys(requirement_keys)]


def matching_provenance(*results) -> bool:
    return bool(results) and all(item.provenance == results[0].provenance for item in results[1:])


def get_required_checks(db: Session, case_id: UUID) -> RequiredChecksResult:
    with db.no_autoflush:
        provenance, _, _ = _load_context(db, case_id)
        return RequiredChecksResult(
            provenance=provenance,
            questions=list_questions(db, case_id=case_id, source_judgment_run_id=provenance.judgment_run_id),
        )


def get_judgment_profile_snapshot(db: Session, case_id: UUID) -> JudgmentProfileResult:
    with db.no_autoflush:
        provenance, _, judgment = _load_context(db, case_id)
        return JudgmentProfileResult(
            provenance=provenance, profile_snapshot=judgment.profile_snapshot,
            profile_completeness=judgment.profile_completeness,
        )
