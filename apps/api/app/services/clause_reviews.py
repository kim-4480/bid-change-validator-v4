"""Backend boundary for storing and reading contract-clause review results."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bidengine.clause_review.contracts import ClauseFinding, finding_to_payload
from ..clause_review_models import ContractClauseFindingRecord, ContractClauseReviewRun
from ..clause_review_schemas import (
    ContractClauseFindingRead,
    ContractClauseReviewCreate,
    ContractClauseReviewRead,
    ContractClauseReviewSummary,
)
from ..models import BidNoticeVersion


class ContractClauseReviewError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _load_version(db: Session, *, notice_id: UUID, version_number: int) -> BidNoticeVersion:
    version = db.scalar(
        select(BidNoticeVersion).where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
        )
    )
    if version is None:
        raise ContractClauseReviewError(
            "NOTICE_VERSION_NOT_FOUND",
            "계약조항을 저장할 공고 버전을 찾을 수 없습니다.",
            status_code=404,
        )
    return version


def create_contract_clause_review(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
    payload: ContractClauseReviewCreate,
) -> ContractClauseReviewRun:
    version = _load_version(db, notice_id=notice_id, version_number=version_number)
    run = ContractClauseReviewRun(notice_version_id=version.id, status=payload.status)
    db.add(run)
    db.flush()

    for finding in payload.findings:
        if finding.notice_version_id not in {None, str(version.id)}:
            raise ContractClauseReviewError(
                "CLAUSE_FINDING_VERSION_MISMATCH",
                "계약조항 결과의 공고 버전이 저장 대상과 일치하지 않습니다.",
            )
        finding_payload = finding_to_payload(finding, payload.findings)
        rfp_value = None
        if any(
            value is not None
            for value in (
                finding.notice_value,
                finding.notice_value_raw,
                finding.notice_value_unit,
            )
        ):
            rfp_value = {
                "value": finding.notice_value,
                "raw": finding.notice_value_raw,
                "unit": finding.notice_value_unit,
            }
        db.add(
            ContractClauseFindingRecord(
                review_run_id=run.id,
                category=finding_payload["category"],
                categories=finding_payload["categories"],
                rule_id=finding.rule_id,
                risk_type=finding_payload["risk_type"],
                risk_types=finding_payload["risk_types"],
                detection_method=finding.detection_method.lower(),
                matched_via=finding.matched_via.lower() if finding.matched_via else None,
                verdict=finding_payload["verdict_label"],
                reason=finding_payload["reason"],
                matched_text=finding_payload["matched_text"],
                rfp_clause_label=finding_payload["clause_label"],
                rfp_chunk_id=finding_payload["chunk_id"],
                rfp_excerpt=finding_payload["excerpt"],
                rfp_value=rfp_value,
                standard=(
                    finding.standard.model_dump(mode="json")
                    if finding.standard is not None
                    else None
                ),
                form=finding.form,
            )
        )
    db.commit()
    return load_contract_clause_review(db, run.id)


def load_contract_clause_review(db: Session, run_id: UUID) -> ContractClauseReviewRun:
    run = db.scalar(
        select(ContractClauseReviewRun)
        .where(ContractClauseReviewRun.id == run_id)
        .options(
            selectinload(ContractClauseReviewRun.notice_version),
            selectinload(ContractClauseReviewRun.findings),
        )
    )
    if run is None:
        raise ContractClauseReviewError(
            "CONTRACT_CLAUSE_REVIEW_NOT_FOUND",
            "계약조항 검토 결과를 찾을 수 없습니다.",
            status_code=404,
        )
    return run


def contract_clause_review_response(run: ContractClauseReviewRun) -> ContractClauseReviewRead:
    return ContractClauseReviewRead(
        id=run.id,
        notice_id=run.notice_version.notice_id,
        notice_version_id=run.notice_version_id,
        version_number=run.notice_version.version_number,
        status=run.status,
        findings=[
            ContractClauseFindingRead.model_validate(item)
            for item in sorted(run.findings, key=lambda item: (item.category, str(item.id)))
        ],
        created_at=run.created_at,
    )


def list_contract_clause_reviews(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
) -> list[ContractClauseReviewSummary]:
    version = _load_version(db, notice_id=notice_id, version_number=version_number)
    runs = db.scalars(
        select(ContractClauseReviewRun)
        .where(ContractClauseReviewRun.notice_version_id == version.id)
        .options(selectinload(ContractClauseReviewRun.findings))
        .order_by(ContractClauseReviewRun.created_at.desc())
    ).all()
    return [
        ContractClauseReviewSummary(
            id=run.id,
            notice_version_id=run.notice_version_id,
            version_number=version.version_number,
            status=run.status,
            finding_count=len(run.findings),
            needs_review_count=sum(item.verdict == "확인 필요" for item in run.findings),
            created_at=run.created_at,
        )
        for run in runs
    ]
