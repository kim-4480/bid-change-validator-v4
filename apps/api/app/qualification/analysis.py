"""Backend service boundary for qualification Requirement analysis persistence."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    StructuredExtractor,
    analyze_qualification_documents,
)
from bidengine.pipeline.analysis_result import RequirementAnalysisResult
from bidengine.contracts import Evidence, EvidenceLocation, QualificationRequirement
from ..analysis_models import (
    QualificationAnalysisRun,
    QualificationEvidenceRecord,
    QualificationRequirementRecord,
)
from ..analysis_schemas import QualificationAnalysisRunRead, QualificationAnalysisRunSummary
from ..models import BidNoticeVersion, NoticeDocument
from .answer_memory import DbAnswerMemory, DbIndustryNameResolver


class QualificationAnalysisError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _load_notice_version(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
) -> BidNoticeVersion:
    version = db.scalar(
        select(BidNoticeVersion)
        .where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
        )
        .options(selectinload(BidNoticeVersion.documents))
    )
    if version is None:
        raise QualificationAnalysisError(
            "NOTICE_VERSION_NOT_FOUND", "분석할 공고 버전을 찾을 수 없습니다."
        )
    return version


def build_qualification_analysis_input(version: BidNoticeVersion) -> QualificationAnalysisInput:
    documents = [
        QualificationDocumentInput(
            document_id=str(document.id),
            file_sha256=document.file_sha256,
            extracted_text_sha256=document.extracted_text_sha256,
            extracted_blocks=list(document.extracted_blocks or []),
        )
        for document in version.documents
        if document.extraction_status == "EXTRACTED" and document.extracted_blocks
    ]
    return QualificationAnalysisInput(
        notice_id=str(version.notice_id),
        notice_version_id=str(version.id),
        documents=documents,
    )


def _persist_result(
    db: Session,
    *,
    version: BidNoticeVersion,
    result: RequirementAnalysisResult,
) -> QualificationAnalysisRun:
    run = QualificationAnalysisRun(
        notice_version_id=version.id,
        contract_version=result.contract_version,
        analysis_kind=result.analysis_kind,
        status=result.status,
        target_chunk_ids=list(result.target_chunk_ids),
        diagnostics=[item.model_dump(mode="json") for item in result.diagnostics],
        dropped_requirements=[
            item.model_dump(mode="json") for item in result.dropped_requirements
        ],
    )
    db.add(run)
    db.flush()

    for requirement in result.requirements:
        db.add(
            QualificationRequirementRecord(
                analysis_run_id=run.id,
                requirement_key=requirement.requirement_key,
                requirement_group_key=requirement.requirement_group_key,
                group_operator=requirement.group_operator,
                type=requirement.type,
                operator=requirement.operator,
                value_json=requirement.value,
                unit=requirement.unit,
                period_months=(
                    Decimal(str(requirement.period_months))
                    if requirement.period_months is not None
                    else None
                ),
                scope=dict(requirement.scope),
                requirement_role=requirement.requirement_role,
                condition_complexity=requirement.condition_complexity,
                required=requirement.required,
                raw=requirement.raw,
                confidence=(
                    Decimal(str(requirement.confidence))
                    if requirement.confidence is not None
                    else None
                ),
                evidence_keys=list(requirement.evidence_keys),
            )
        )

    for evidence in result.evidence:
        db.add(
            QualificationEvidenceRecord(
                analysis_run_id=run.id,
                evidence_key=evidence.evidence_key,
                source_type=evidence.source_type,
                document_id=evidence.document_id,
                notice_version_id=evidence.notice_version_id,
                case_id=evidence.case_id,
                chunk_id=evidence.chunk_id,
                location=evidence.location.model_dump(mode="json"),
                quote=evidence.quote,
                source_sha256=evidence.source_sha256,
                extracted_text_sha256=evidence.extracted_text_sha256,
            )
        )

    db.commit()
    return load_qualification_analysis_run(db, run.id)


def run_qualification_analysis(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
    structured_extract: StructuredExtractor,
) -> QualificationAnalysisRun:
    version = _load_notice_version(
        db, notice_id=notice_id, version_number=version_number
    )
    analysis_input = build_qualification_analysis_input(version)
    # 같은 조항은 같은 답 — 조항 라벨·극성·조항 선택의 첫 답을 DB 에 두고 다시 묻지 않는다. 모델이 temperature 를
    # 받지 않고 seed 로도 답이 고정되지 않아, 이것 없이는 같은 공고를 다시 분석하면 요건이 달라졌다.
    # 업종 이름은 기준정보 테이블로 코드화한다.
    result = analyze_qualification_documents(
        analysis_input,
        structured_extract=structured_extract,
        industry_resolver=DbIndustryNameResolver(db),
        labeling_memory=DbAnswerMemory(db, "label"),
        polarity_memory=DbAnswerMemory(db, "polarity"),
        selection_memory=DbAnswerMemory(db, "selection"),
        # 기억은 모델별로 갈린다 — 모델을 바꾸면 예전 모델의 답을 쓰지 않는다.
        memory_namespace=getattr(structured_extract, "model", None) or type(structured_extract).__name__,
    )
    return _persist_result(db, version=version, result=result)


def load_qualification_analysis_run(
    db: Session, run_id: UUID
) -> QualificationAnalysisRun:
    run = db.scalar(
        select(QualificationAnalysisRun)
        .where(QualificationAnalysisRun.id == run_id)
        .options(
            selectinload(QualificationAnalysisRun.notice_version),
            selectinload(QualificationAnalysisRun.requirements),
            selectinload(QualificationAnalysisRun.evidence),
        )
    )
    if run is None:
        raise QualificationAnalysisError(
            "ANALYSIS_RUN_NOT_FOUND", "자격요건 분석 실행을 찾을 수 없습니다."
        )
    return run


def analysis_run_response(run: QualificationAnalysisRun) -> QualificationAnalysisRunRead:
    version = run.notice_version
    requirements = [
        QualificationRequirement(
            requirement_key=item.requirement_key,
            requirement_group_key=item.requirement_group_key,
            group_operator=item.group_operator,
            notice_version_id=str(version.id),
            type=item.type,
            operator=item.operator,
            value=item.value_json,
            unit=item.unit,
            period_months=float(item.period_months) if item.period_months is not None else None,
            scope=dict(item.scope or {}),
            requirement_role=item.requirement_role,
            condition_complexity=item.condition_complexity,
            required=item.required,
            raw=item.raw,
            confidence=float(item.confidence) if item.confidence is not None else None,
            evidence_keys=list(item.evidence_keys or []),
        )
        for item in sorted(run.requirements, key=lambda value: value.requirement_key)
    ]
    evidence = [
        Evidence(
            evidence_key=item.evidence_key,
            source_type=item.source_type,
            document_id=item.document_id,
            notice_version_id=item.notice_version_id,
            case_id=item.case_id,
            chunk_id=item.chunk_id,
            location=EvidenceLocation(**dict(item.location or {})),
            quote=item.quote,
            source_sha256=item.source_sha256,
            extracted_text_sha256=item.extracted_text_sha256,
        )
        for item in sorted(run.evidence, key=lambda value: value.evidence_key)
    ]
    return QualificationAnalysisRunRead(
        id=run.id,
        notice_id=version.notice_id,
        notice_version_id=version.id,
        version_number=version.version_number,
        contract_version=run.contract_version,
        analysis_kind=run.analysis_kind,
        status=run.status,
        target_chunk_ids=list(run.target_chunk_ids or []),
        diagnostics=list(run.diagnostics or []),
        dropped_requirements=list(run.dropped_requirements or []),
        requirements=requirements,
        evidence=evidence,
        created_at=run.created_at,
    )


def list_qualification_analysis_runs(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int,
) -> list[QualificationAnalysisRunSummary]:
    version = _load_notice_version(db, notice_id=notice_id, version_number=version_number)
    runs = db.scalars(
        select(QualificationAnalysisRun)
        .where(QualificationAnalysisRun.notice_version_id == version.id)
        .options(
            selectinload(QualificationAnalysisRun.requirements),
            selectinload(QualificationAnalysisRun.evidence),
        )
        .order_by(QualificationAnalysisRun.created_at.desc())
    ).all()
    return [
        QualificationAnalysisRunSummary(
            id=run.id,
            notice_version_id=version.id,
            version_number=version.version_number,
            contract_version=run.contract_version,
            status=run.status,
            requirement_count=len(run.requirements),
            evidence_count=len(run.evidence),
            created_at=run.created_at,
        )
        for run in runs
    ]
