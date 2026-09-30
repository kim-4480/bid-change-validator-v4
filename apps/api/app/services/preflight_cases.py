import hashlib
from datetime import datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    BidNotice,
    BidNoticeVersion,
    Company,
    PreflightCase,
    ProposalDocument,
)
from ..schemas import PreflightCaseCreate, ProposalDocumentRole
from .document_extraction import extract_into_document
from .document_storage import build_document_storage, safe_storage_segment


KST = ZoneInfo("Asia/Seoul")
ALLOWED_PROPOSAL_EXTENSIONS = {".hwp", ".hwpx", ".pdf", ".docx", ".txt"}


class PreflightValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class DuplicateProposalDocumentError(ValueError):
    pass


def _notice_version(
    db: Session,
    *,
    notice_id: UUID,
    version_number: int | None,
    current_default: bool,
) -> BidNoticeVersion | None:
    statement = select(BidNoticeVersion).where(BidNoticeVersion.notice_id == notice_id)
    if version_number is not None:
        statement = statement.where(BidNoticeVersion.version_number == version_number)
    elif current_default:
        statement = statement.where(BidNoticeVersion.is_current.is_(True))
    else:
        return None
    return db.scalar(statement)


def create_preflight_case(db: Session, payload: PreflightCaseCreate) -> PreflightCase:
    notice = db.get(BidNotice, payload.notice_id)
    if notice is None:
        raise PreflightValidationError("NOTICE_NOT_FOUND", "입찰공고를 찾을 수 없습니다.")
    if payload.company_id is not None and db.get(Company, payload.company_id) is None:
        raise PreflightValidationError("COMPANY_NOT_FOUND", "회사 프로필을 찾을 수 없습니다.")

    current_version = _notice_version(
        db,
        notice_id=notice.id,
        version_number=payload.current_version_number,
        current_default=True,
    )
    if current_version is None:
        raise PreflightValidationError(
            "NOTICE_VERSION_NOT_FOUND",
            "현재 공고 버전을 찾을 수 없습니다.",
        )
    baseline_version = _notice_version(
        db,
        notice_id=notice.id,
        version_number=payload.baseline_version_number,
        current_default=False,
    )
    if payload.baseline_version_number is not None and baseline_version is None:
        raise PreflightValidationError(
            "NOTICE_VERSION_NOT_FOUND",
            "기준 공고 버전을 찾을 수 없습니다.",
        )
    if baseline_version is not None and baseline_version.version_number >= current_version.version_number:
        raise PreflightValidationError(
            "INVALID_VERSION_RANGE",
            "기준 공고 버전은 현재 공고 버전보다 앞선 차수여야 합니다.",
        )

    case = PreflightCase(
        company_id=payload.company_id,
        notice_id=notice.id,
        baseline_version_id=baseline_version.id if baseline_version else None,
        current_version_id=current_version.id,
        title=payload.title or f"{notice.title} 사전검토",
        status="DRAFT",
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def store_proposal_document(
    db: Session,
    *,
    case: PreflightCase,
    filename: str,
    content_type: str | None,
    role: ProposalDocumentRole,
    source: BinaryIO,
    settings: Settings,
) -> ProposalDocument:
    normalized_name = Path(filename).name.strip()
    if not normalized_name:
        raise PreflightValidationError("INVALID_FILE_NAME", "파일명이 비어 있습니다.")
    suffix = Path(normalized_name).suffix.lower()
    if suffix not in ALLOWED_PROPOSAL_EXTENSIONS:
        raise PreflightValidationError(
            "UNSUPPORTED_FILE_TYPE",
            "HWP, HWPX, PDF, DOCX, TXT 파일만 업로드할 수 있습니다.",
        )

    sha256 = hashlib.sha256()
    size = 0
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temp:
        source.seek(0)
        while chunk := source.read(64 * 1024):
            size += len(chunk)
            if size > settings.document_max_file_size_bytes:
                raise PreflightValidationError(
                    "FILE_TOO_LARGE",
                    "파일 크기가 허용 한도를 초과했습니다.",
                )
            sha256.update(chunk)
            temp.write(chunk)
        if size == 0:
            raise PreflightValidationError("EMPTY_FILE", "빈 파일은 업로드할 수 없습니다.")
        digest = sha256.hexdigest()
        duplicate = db.scalar(
            select(ProposalDocument).where(
                ProposalDocument.case_id == case.id,
                ProposalDocument.file_sha256 == digest,
            )
        )
        if duplicate is not None:
            raise DuplicateProposalDocumentError("같은 파일이 이미 업로드되어 있습니다.")

        latest_order = db.scalar(
            select(func.max(ProposalDocument.document_order)).where(
                ProposalDocument.case_id == case.id
            )
        )
        next_order = (latest_order if latest_order is not None else -1) + 1
        document_id = uuid4()
        safe_name = safe_storage_segment(normalized_name, f"document-{document_id}")
        storage, prefix = build_document_storage(settings)
        storage_key = f"proposals/{case.id}/{document_id}/{safe_name}"
        if prefix:
            storage_key = f"{prefix}/{storage_key}"
        stored_key = storage.put(storage_key, temp, content_type)

        document = ProposalDocument(
            id=document_id,
            case_id=case.id,
            document_order=next_order,
            role=role.value,
            name=normalized_name,
            storage_status="STORED",
            storage_key=stored_key,
            content_type=content_type,
            file_size_bytes=size,
            file_sha256=digest,
            stored_at=datetime.now(KST),
        )
        extract_into_document(document, temp)
        db.add(document)
        if document.extraction_status == "EXTRACTED":
            case.status = "READY"
        db.commit()
        db.refresh(document)
        return document
