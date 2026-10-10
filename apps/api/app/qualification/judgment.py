"""Backend service for deterministic qualification judgment and persistence."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bidengine.contracts import Judgment
from bidengine.judgment.rules import (
    RULE_VERSION,
    CompanyProfileSnapshot,
    ProfileCertificationFact,
    ProfileCompleteness,
    ProfileIndustryFact,
    ProfilePerformanceFact,
    ProfileStaffFact,
    ProfileStaffRoleFact,
    judge_requirements,
)
from .analysis import no_restriction_stated
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import CompanyQualificationProfileCompleteness, QualificationJudgmentRecord, QualificationJudgmentRun
from ..judgment_schemas import QualificationJudgmentRunRead, QualificationJudgmentRunSummary, QualificationProfileCompletenessRead, QualificationProfileCompletenessUpdate
from ..models import Company, CompanyIndustry, CompanyPerformance, PreflightCase
from .analysis import (
    QualificationAnalysisError,
    analysis_run_response,
    build_qualification_analysis_input,
    is_qualification_analysis_run_stale,
    load_latest_current_qualification_analysis_run,
    load_qualification_analysis_run,
)
from .impact_adapter import current_grounded_requirement_keys
from ..services.participation_limits import notice_api_grounded_keys


class QualificationJudgmentError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def grounded_keys_for_analysis(run: QualificationAnalysisRun, analysis) -> set[str]:
    # An incomplete run cannot prove any requirement is grounded. Keep test
    # doubles and partially loaded historical rows fail-closed as well.
    notice_version = getattr(run, "notice_version", None)
    if notice_version is None:
        return set()
    grounded = current_grounded_requirement_keys(
        analysis.requirements, analysis.evidence,
        build_qualification_analysis_input(notice_version).documents,
        notice_version_id=str(run.notice_version_id),
    )
    # 나라장터 면허제한·참가가능지역에서 온 요건은 인용할 문서가 없다. 저장된 조회 값에 그 값이 지금도 있으면 근거가 있다.
    return grounded | notice_api_grounded_keys(
        analysis.requirements, getattr(notice_version, "participation_limits", None),
    )


def load_judgment_analysis(db: Session, run_id: UUID) -> QualificationAnalysisRun:
    """Translate analysis lookup failures at the shared judgment service boundary."""
    try:
        return load_qualification_analysis_run(db, run_id)
    except QualificationAnalysisError as error:
        raise QualificationJudgmentError(error.code, error.message, status_code=404) from error


_COMPANY_LOAD_OPTIONS = (
    selectinload(Company.industries).selectinload(CompanyIndustry.industry),
    selectinload(Company.staff),
    selectinload(Company.staff_roles),
    selectinload(Company.performances).selectinload(CompanyPerformance.experience_fields),
    selectinload(Company.certifications),
)


def _load_company(db: Session, company_id: UUID) -> Company:
    company = db.scalar(select(Company).where(Company.id == company_id).options(*_COMPANY_LOAD_OPTIONS))
    if company is None:
        raise QualificationJudgmentError("COMPANY_NOT_FOUND", "회사 프로필을 찾을 수 없습니다.", status_code=404)
    return company


def _load_case(db: Session, case_id: UUID) -> PreflightCase:
    case = db.get(PreflightCase, case_id)
    if case is None:
        raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "사전검토 건을 찾을 수 없습니다.", status_code=404)
    return case


def _record_to_completeness(record: CompanyQualificationProfileCompleteness | None) -> ProfileCompleteness:
    if record is None:
        return ProfileCompleteness()
    return ProfileCompleteness(
        region=record.region_complete,
        company_size=record.company_size_complete,
        industries=record.industries_complete,
        staff_total=record.staff_total_complete,
        staff_roles=record.staff_roles_complete,
        performances=record.performances_complete,
        certifications=record.certifications_complete,
    )


def get_profile_completeness(db: Session, company_id: UUID) -> QualificationProfileCompletenessRead:
    _load_company(db, company_id)
    record = db.get(CompanyQualificationProfileCompleteness, company_id)
    return QualificationProfileCompletenessRead(
        company_id=company_id,
        completeness=_record_to_completeness(record),
        persisted=record is not None,
        updated_at=record.updated_at if record is not None else None,
    )


def update_profile_completeness(db: Session, company_id: UUID, payload: QualificationProfileCompletenessUpdate) -> QualificationProfileCompletenessRead:
    _load_company(db, company_id)
    record = db.get(CompanyQualificationProfileCompleteness, company_id)
    if record is None:
        defaults = ProfileCompleteness()
        record = CompanyQualificationProfileCompleteness(
            company_id=company_id,
            region_complete=defaults.region,
            company_size_complete=defaults.company_size,
            industries_complete=defaults.industries,
            staff_total_complete=defaults.staff_total,
            staff_roles_complete=defaults.staff_roles,
            performances_complete=defaults.performances,
            certifications_complete=defaults.certifications,
        )
        db.add(record)

    field_map = {
        "region": "region_complete",
        "company_size": "company_size_complete",
        "industries": "industries_complete",
        "staff_total": "staff_total_complete",
        "staff_roles": "staff_roles_complete",
        "performances": "performances_complete",
        "certifications": "certifications_complete",
    }
    for field in payload.model_fields_set:
        setattr(record, field_map[field], getattr(payload, field))
    db.commit()
    db.refresh(record)
    return QualificationProfileCompletenessRead(
        company_id=company_id,
        completeness=_record_to_completeness(record),
        persisted=True,
        updated_at=record.updated_at,
    )


def build_company_profile_snapshot(company: Company, completeness: ProfileCompleteness) -> CompanyProfileSnapshot:
    staff = None
    if company.staff is not None:
        staff = ProfileStaffFact(
            total_count=company.staff.total_count,
            verified=company.staff.verified,
            roles=[ProfileStaffRoleFact(role_name=item.role_name, headcount=item.headcount, career_years=float(item.career_years) if item.career_years is not None else None, verified=item.verified) for item in sorted(company.staff_roles, key=lambda x: x.role_name)],
        )
    return CompanyProfileSnapshot(
        company_id=str(company.id),
        region_code=company.region_code,
        region_name=company.region_name,
        company_size=company.company_size,
        industries=[ProfileIndustryFact(code=item.industry_code, name=item.industry.name, verified=item.verified) for item in sorted(company.industries, key=lambda x: x.industry_code)],
        staff=staff,
        performances=[
            ProfilePerformanceFact(
                ref=str(item.id), name=item.name, client_name=item.client_name,
                client_institution_code=item.client_institution_code, amount=int(item.amount),
                started_at=item.started_at, completed_at=item.completed_at,
                completed_year=item.completed_year,
                fields=sorted(field.field_name for field in item.experience_fields), verified=item.verified,
            )
            for item in sorted(company.performances, key=lambda x: (x.completed_at or date(x.completed_year or 1900, 12, 31), str(x.id)), reverse=True)
        ],
        certifications=[
            ProfileCertificationFact(ref=str(item.id), name=item.name, certification_code=item.certification_code, issuer_name=item.issuer_name, issued_at=item.issued_at, expires_at=item.expires_at, verified=item.verified)
            for item in sorted(company.certifications, key=lambda x: (x.name, str(x.id)))
        ],
        completeness=completeness,
    )


def _select_analysis_run(db: Session, case: PreflightCase, analysis_run_id: UUID | None) -> QualificationAnalysisRun:
    if analysis_run_id is not None:
        run = load_judgment_analysis(db, analysis_run_id)
    else:
        run = load_latest_current_qualification_analysis_run(
            db, notice_version_id=case.current_version_id, include_failed=True
        )
        if run is None:
            raise QualificationJudgmentError("QUALIFICATION_ANALYSIS_REQUIRED", "현재 공고 버전의 자격요건 분석 결과가 필요합니다.")
    if run.notice_version_id != case.current_version_id:
        raise QualificationJudgmentError("ANALYSIS_VERSION_MISMATCH", "선택한 분석 결과가 사전검토 건의 현재 공고 버전과 일치하지 않습니다.", status_code=422)
    if run.status == "FAILED":
        raise QualificationJudgmentError("QUALIFICATION_ANALYSIS_FAILED", "실패한 자격요건 분석 결과로는 판정할 수 없습니다.")
    if is_qualification_analysis_run_stale(run):
        raise QualificationJudgmentError(
            "QUALIFICATION_ANALYSIS_STALE",
            "문서가 재추출되어 자격요건을 다시 분석해야 합니다.",
        )
    return run


def run_qualification_judgment(db: Session, *, case_id: UUID, analysis_run_id: UUID | None = None, reference_date: date | None = None) -> QualificationJudgmentRun:
    case = _load_case(db, case_id)
    if case.company_id is None:
        raise QualificationJudgmentError("COMPANY_PROFILE_REQUIRED", "자격 판정을 위해 사전검토 건에 회사 프로필이 필요합니다.", status_code=422)
    company = _load_company(db, case.company_id)
    completeness = _record_to_completeness(db.get(CompanyQualificationProfileCompleteness, company.id))
    profile = build_company_profile_snapshot(company, completeness)
    analysis_run = _select_analysis_run(db, case, analysis_run_id)
    analysis = analysis_run_response(analysis_run)
    evaluation = judge_requirements(analysis.requirements, profile, preflight_case_id=str(case.id), reference_date=reference_date or date.today(), analysis_status=analysis_run.status, coverage_complete=analysis.verdict_complete, no_restriction_stated=no_restriction_stated(analysis), grounded_requirement_keys=grounded_keys_for_analysis(analysis_run, analysis))
    overall_status = evaluation.overall_status

    run = QualificationJudgmentRun(
        preflight_case_id=case.id,
        analysis_run_id=analysis_run.id,
        company_id=case.company_id,
        notice_version_id=case.current_version_id,
        overall_status=overall_status,
        rule_version=RULE_VERSION,
        reference_date=reference_date or date.today(),
        profile_snapshot=profile.model_dump(mode="json"),
        analysis_status=analysis_run.status,
    )
    db.add(run)
    db.flush()
    for item in evaluation.judgments:
        db.add(QualificationJudgmentRecord(
            judgment_run_id=run.id, judgment_key=item.judgment_key, requirement_key=item.requirement_key,
            status=item.status, basis_type=item.basis_type, evidence_held=item.evidence_held,
            value_source=item.value_source, evidence_status=item.evidence_status,
            reason_code=item.reason_code, unknown_reason=item.unknown_reason,
            requires_evidence=item.requires_evidence,
            profile_refs=list(item.profile_refs), requirement_evidence_keys=list(item.requirement_evidence_keys),
            rule_version=item.rule_version,
        ))
    db.commit()
    return load_qualification_judgment_run(db, run.id)


def load_qualification_judgment_run(db: Session, run_id: UUID) -> QualificationJudgmentRun:
    run = db.scalar(select(QualificationJudgmentRun).where(QualificationJudgmentRun.id == run_id).options(selectinload(QualificationJudgmentRun.judgments)))
    if run is None:
        raise QualificationJudgmentError("JUDGMENT_RUN_NOT_FOUND", "자격 판정 실행을 찾을 수 없습니다.", status_code=404)
    return run


def judgment_run_response(run: QualificationJudgmentRun) -> QualificationJudgmentRunRead:
    snapshot = CompanyProfileSnapshot.model_validate(dict(run.profile_snapshot or {}))
    judgments = [Judgment(
        judgment_key=item.judgment_key, preflight_case_id=str(run.preflight_case_id), notice_version_id=str(run.notice_version_id),
        requirement_key=item.requirement_key, status=item.status, basis_type=item.basis_type,
        evidence_held=item.evidence_held, value_source=item.value_source,
        evidence_status=item.evidence_status, reason_code=item.reason_code,
        unknown_reason=item.unknown_reason, requires_evidence=item.requires_evidence,
        profile_refs=list(item.profile_refs or []), requirement_evidence_keys=list(item.requirement_evidence_keys or []), rule_version=item.rule_version,
    ) for item in sorted(run.judgments, key=lambda x: x.requirement_key)]
    return QualificationJudgmentRunRead(
        id=run.id, preflight_case_id=run.preflight_case_id, analysis_run_id=run.analysis_run_id,
        company_id=run.company_id, notice_version_id=run.notice_version_id,
        overall_status=run.overall_status, rule_version=run.rule_version,
        reference_date=run.reference_date, analysis_status=run.analysis_status,
        profile_completeness=snapshot.completeness, profile_snapshot=snapshot.model_dump(mode="json"),
        judgments=judgments, created_at=run.created_at,
    )


def list_qualification_judgment_runs(db: Session, *, case_id: UUID) -> list[QualificationJudgmentRunSummary]:
    _load_case(db, case_id)
    runs = db.scalars(select(QualificationJudgmentRun).where(QualificationJudgmentRun.preflight_case_id == case_id).options(selectinload(QualificationJudgmentRun.judgments)).order_by(QualificationJudgmentRun.created_at.desc())).all()
    return [QualificationJudgmentRunSummary(
        id=run.id, analysis_run_id=run.analysis_run_id, company_id=run.company_id,
        notice_version_id=run.notice_version_id, overall_status=run.overall_status,
        rule_version=run.rule_version, reference_date=run.reference_date,
        analysis_status=run.analysis_status, judgment_count=len(run.judgments),
        unknown_count=sum(item.status == "UNKNOWN" for item in run.judgments),
        unsatisfied_count=sum(item.status == "UNSATISFIED" for item in run.judgments),
        created_at=run.created_at,
    ) for run in runs]
