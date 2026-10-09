"""Read-only proposals; only confirm delegates to existing write services."""

from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ask_back_schemas import QualificationAnswerCreate, QualificationAnswerRead
from ..models import PreflightCase
from ..qualification.analysis import (
    analysis_run_response,
    load_latest_current_qualification_analysis_run,
)
from ..qualification.ask_back import answer_and_rejudge
from ..qualification.judgment import (
    QualificationJudgmentError, list_qualification_judgment_runs,
    load_qualification_judgment_run,
)
from ..qualification.revalidation import run_qualification_revalidation
from bidengine.judgment.rules import RULE_VERSION
from bidengine.diff.requirement_diff import RequirementChange, diff_requirements
from ..revalidation_schemas import QualificationRevalidationCreate, QualificationRevalidationRead
from .contracts import (
    ActionInput, AnswerProposal, ConfirmAction, RevalidationProposal,
    RevalidationProvenance, VersionState,
)
from .product_tools import get_required_checks


class ChangedNoticeResult(BaseModel):
    provenance: RevalidationProvenance
    changes: list[RequirementChange]


def propose_answer(db: Session, case_id: UUID, requirement_key: str, user_input: ActionInput) -> AnswerProposal:
    checks = get_required_checks(db, case_id)
    question = next((q for q in checks.questions if q.requirement_key == requirement_key), None)
    if question is None or not question.askable:
        raise QualificationJudgmentError("REQUIREMENT_NOT_ASKABLE", "사용자 답변이 가능한 UNKNOWN 요건이 아닙니다.")
    if checks.provenance.rule_version != RULE_VERSION:
        raise QualificationJudgmentError("STALE_ACTION_CONTEXT", "현재 규칙으로 다시 판정해야 합니다.")
    return AnswerProposal(expected=checks.provenance, requirement_key=requirement_key, user_input=user_input)


def get_changed_notice(db: Session, case_id: UUID) -> ChangedNoticeResult:
    with db.no_autoflush:
        case = db.get(PreflightCase, case_id)
        if case is None:
            raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "검토 건이 없습니다.", status_code=404)
        if not case.company_id or not case.baseline_version_id or case.baseline_version_id == case.current_version_id:
            raise QualificationJudgmentError("CHANGED_NOTICE_REQUIRED", "서로 다른 기준·현재 버전과 회사가 필요합니다.")
        runs = list_qualification_judgment_runs(db, case_id=case_id)
        states, analyses = [], []
        for version_id in (case.baseline_version_id, case.current_version_id):
            record = load_latest_current_qualification_analysis_run(
                db, notice_version_id=version_id, include_failed=True
            )
            if record is None:
                raise QualificationJudgmentError("QUALIFICATION_ANALYSIS_REQUIRED", "두 버전의 분석이 필요합니다.")
            if record.notice_version_id != version_id or record.notice_version.notice_id != case.notice_id:
                raise QualificationJudgmentError("ANALYSIS_VERSION_MISMATCH", "분석의 공고 버전이 다릅니다.")
            if record.status not in ("SUCCEEDED", "PARTIAL"):
                raise QualificationJudgmentError("QUALIFICATION_ANALYSIS_FAILED", "실패한 분석으로 비교할 수 없습니다.")
            analysis = analysis_run_response(record)
            evidence = {e.evidence_key for e in analysis.evidence}
            if any(e.notice_version_id != str(version_id) for e in analysis.evidence):
                raise QualificationJudgmentError("EVIDENCE_VERSION_MISMATCH", "근거 버전이 다릅니다.")
            if any(r.notice_version_id != str(version_id) for r in analysis.requirements):
                raise QualificationJudgmentError("ANALYSIS_VERSION_MISMATCH", "요건 버전이 다릅니다.")
            if not {key for r in analysis.requirements for key in r.evidence_keys} <= evidence:
                raise QualificationJudgmentError("EVIDENCE_NOT_FOUND", "참조한 근거가 없습니다.")
            candidates = [r for r in runs if r.notice_version_id == version_id]
            selected = max(candidates, key=lambda r: (r.created_at, str(r.id))) if candidates else None
            states.append(VersionState(
                notice_version_id=version_id, version_number=analysis.version_number,
                analysis_run_id=analysis.id, analysis_status=analysis.status,
                judgment_run_id=selected.id if selected else None,
            ))
            analyses.append(analysis)
        baseline, current = states
        if baseline.judgment_run_id is None:
            raise QualificationJudgmentError("BASELINE_JUDGMENT_REQUIRED", "기준 버전의 판정이 필요합니다.")
        source = load_qualification_judgment_run(db, baseline.judgment_run_id)
        if (source.preflight_case_id != case.id or source.company_id != case.company_id
                or source.notice_version_id != baseline.notice_version_id
                or source.profile_snapshot.get("company_id") != str(case.company_id)):
            raise QualificationJudgmentError("JUDGMENT_CASE_MISMATCH", "기준 판정의 문맥이 다릅니다.")
        if source.analysis_run_id != baseline.analysis_run_id or source.rule_version != RULE_VERSION:
            raise QualificationJudgmentError("STALE_ACTION_CONTEXT", "최신 분석·규칙으로 기준 판정이 필요합니다.")
        if source.analysis_status != baseline.analysis_status:
            raise QualificationJudgmentError("ANALYSIS_STATUS_MISMATCH", "기준 분석 상태가 다릅니다.")
        if {r.requirement_key for r in source.judgments} != {r.requirement_key for r in analyses[0].requirements}:
            raise QualificationJudgmentError("REQUIREMENT_JUDGMENT_MISMATCH", "기준 요건과 판정 연결이 불완전합니다.")
        if not {key for r in source.judgments for key in r.requirement_evidence_keys} <= {e.evidence_key for e in analyses[0].evidence}:
            raise QualificationJudgmentError("EVIDENCE_NOT_FOUND", "기준 판정의 근거가 없습니다.")
        return ChangedNoticeResult(
            provenance=RevalidationProvenance(
                case_id=case.id, notice_id=case.notice_id, company_id=case.company_id,
                baseline=baseline, current=current, rule_version=source.rule_version,
            ),
            changes=diff_requirements(analyses[0].requirements, analyses[1].requirements),
        )


def confirm_action(db: Session, payload: ConfirmAction) -> QualificationAnswerRead | QualificationRevalidationRead:
    action = payload.action
    case_id = action.expected.case_id
    # Refresh under the same case lock used by the existing write services.
    # Reject pending caller edits: their commit must not hitchhike on confirmation.
    if db.new or db.dirty or db.deleted:
        raise QualificationJudgmentError("DIRTY_ACTION_SESSION", "독립된 트랜잭션에서 확인해야 합니다.")
    with db.no_autoflush:
        case = db.scalar(select(PreflightCase).where(PreflightCase.id == case_id)
                         .with_for_update().execution_options(populate_existing=True))
        if case is None:
            raise QualificationJudgmentError("PREFLIGHT_CASE_NOT_FOUND", "검토 건이 없습니다.", status_code=404)
        db.expire_all()
        if isinstance(action, AnswerProposal):
            fresh = get_required_checks(db, case_id)
            if fresh.provenance != action.expected:
                raise QualificationJudgmentError("STALE_ACTION_CONTEXT", "제안 이후 판정 문맥이 변경되었습니다.")
            propose_answer(db, case_id, action.requirement_key, action.user_input)
            return answer_and_rejudge(db, case_id=case_id, payload=QualificationAnswerCreate(
                source_judgment_run_id=action.expected.judgment_run_id,
                requirement_key=action.requirement_key, **action.user_input.model_dump(),
            ))
        fresh = get_changed_notice(db, case_id)
        if fresh.provenance != action.expected:
            raise QualificationJudgmentError("STALE_ACTION_CONTEXT", "제안 이후 버전·분석·판정 문맥이 변경되었습니다.")
        return run_qualification_revalidation(db, case_id=case_id, payload=QualificationRevalidationCreate(
            source_judgment_run_id=fresh.provenance.baseline.judgment_run_id,
            baseline_analysis_run_id=fresh.provenance.baseline.analysis_run_id,
            current_analysis_run_id=fresh.provenance.current.analysis_run_id,
        ))
