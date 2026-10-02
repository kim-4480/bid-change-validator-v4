from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import authorize_case_access, get_optional_current_user
from ..auth_models import AppUser
from ..config import get_settings
from ..database import get_db
from ..errors import ApiError
from ..models import BidNotice, BidNoticeVersion, PreflightCase, ProposalDocument
from ..schemas import (
    NoticeDocumentTextRead,
    PreflightCaseCreate,
    PreflightCaseRead,
    PreflightCaseSearchResponse,
    ProposalDocumentRead,
    ProposalDocumentRole,
)
from ..services.preflight_cases import (
    DuplicateProposalDocumentError,
    PreflightValidationError,
    create_preflight_case,
    store_proposal_document,
)
from ..services.document_storage import build_s3_client


router = APIRouter(prefix="/api/v1/preflight-cases", tags=["preflight cases"])


def _case_read(db: Session, case: PreflightCase) -> PreflightCaseRead:
    notice = db.get(BidNotice, case.notice_id)
    current_version = db.get(BidNoticeVersion, case.current_version_id)
    baseline_version = (
        db.get(BidNoticeVersion, case.baseline_version_id)
        if case.baseline_version_id is not None
        else None
    )
    if notice is None or current_version is None:
        raise ApiError(500, "PREFLIGHT_CASE_INVALID", "검토 건의 공고 연결 정보가 손상되었습니다.")
    documents = db.scalars(
        select(ProposalDocument)
        .where(ProposalDocument.case_id == case.id)
        .order_by(ProposalDocument.document_order)
    ).all()
    return PreflightCaseRead(
        id=case.id,
        company_id=case.company_id,
        notice_id=case.notice_id,
        bid_notice_no=notice.bid_notice_no,
        notice_title=notice.title,
        title=case.title,
        status=case.status,
        baseline_version_id=case.baseline_version_id,
        baseline_version_number=(baseline_version.version_number if baseline_version else None),
        current_version_id=case.current_version_id,
        current_version_number=current_version.version_number,
        documents=[ProposalDocumentRead.model_validate(document) for document in documents],
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


def _get_case(db: Session, case_id: UUID) -> PreflightCase:
    case = db.get(PreflightCase, case_id)
    if case is None:
        raise ApiError(404, "PREFLIGHT_CASE_NOT_FOUND", "검토 건을 찾을 수 없습니다.")
    return case


def _get_document(db: Session, case_id: UUID, document_id: UUID) -> ProposalDocument:
    document = db.scalar(
        select(ProposalDocument).where(
            ProposalDocument.id == document_id,
            ProposalDocument.case_id == case_id,
        )
    )
    if document is None:
        raise ApiError(404, "PROPOSAL_DOCUMENT_NOT_FOUND", "제안서 파일을 찾을 수 없습니다.")
    return document


def _render_content_type(document: ProposalDocument) -> str:
    name = document.name.lower()
    if document.content_type == "application/pdf" or name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith(".hwpx") or document.text_extractor == "HWPX_XML":
        return "application/hwp+zip"
    if name.endswith(".hwp") or document.text_extractor == "HWP5_BODYTEXT":
        return "application/x-hwp"
    return document.content_type or "application/octet-stream"


def _serve_document(document: ProposalDocument, *, inline: bool) -> Response:
    if document.storage_status != "STORED":
        raise ApiError(409, "PROPOSAL_DOCUMENT_NOT_AVAILABLE", "저장된 제안서 파일이 없습니다.")
    settings = get_settings()
    media_type = _render_content_type(document)
    backend = settings.document_storage_backend.strip().upper()
    if backend == "LOCAL":
        root = Path(settings.document_storage_path).resolve()
        target = (root / document.storage_key).resolve()
        if root not in target.parents or not target.is_file():
            raise ApiError(404, "PROPOSAL_DOCUMENT_FILE_MISSING", "저장된 제안서 파일이 없습니다.")
        return FileResponse(
            target,
            filename=None if inline else document.name,
            media_type=media_type,
        )
    if backend == "S3":
        if not settings.document_s3_bucket:
            raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "S3 저장소 설정이 없습니다.")
        params = {
            "Bucket": settings.document_s3_bucket,
            "Key": document.storage_key,
            "ResponseContentType": media_type,
        }
        if inline:
            params["ResponseContentDisposition"] = "inline"
        s3 = build_s3_client(
            region=settings.aws_region,
            endpoint_url=settings.document_s3_endpoint_url,
        )
        url = s3.generate_presigned_url("get_object", Params=params, ExpiresIn=300)
        return RedirectResponse(url, status_code=307)
    raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "첨부파일 저장소 설정이 잘못되었습니다.")


@router.post("", response_model=PreflightCaseRead, status_code=201)
def create_case(
    payload: PreflightCaseCreate,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> PreflightCaseRead:
    if user is not None and user.role != "SYSTEM_ADMIN":
        if user.company_id is None:
            raise ApiError(403, "COMPANY_PROFILE_REQUIRED", "소속 회사 프로필이 필요합니다.")
        if payload.company_id is not None and payload.company_id != user.company_id:
            raise ApiError(403, "COMPANY_ACCESS_DENIED", "다른 회사의 검토 건을 만들 수 없습니다.")
        payload = payload.model_copy(update={"company_id": user.company_id})
    try:
        case = create_preflight_case(db, payload)
    except PreflightValidationError as error:
        status_code = 404 if error.code.endswith("NOT_FOUND") else 422
        raise ApiError(status_code, error.code, error.message) from error
    return _case_read(db, case)


@router.get("", response_model=PreflightCaseSearchResponse)
def list_cases(
    notice_id: UUID | None = None,
    company_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> PreflightCaseSearchResponse:
    filters = []
    if notice_id is not None:
        filters.append(PreflightCase.notice_id == notice_id)
    if user is not None and user.role != "SYSTEM_ADMIN":
        if company_id is not None and company_id != user.company_id:
            raise ApiError(403, "COMPANY_ACCESS_DENIED", "다른 회사의 검토 건에는 접근할 수 없습니다.")
        if user.company_id is None:
            raise ApiError(403, "COMPANY_PROFILE_REQUIRED", "소속 회사 프로필이 필요합니다.")
        filters.append(PreflightCase.company_id == user.company_id)
    elif company_id is not None:
        filters.append(PreflightCase.company_id == company_id)
    total = db.scalar(select(func.count()).select_from(PreflightCase).where(*filters)) or 0
    cases = db.scalars(
        select(PreflightCase)
        .where(*filters)
        .order_by(PreflightCase.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return PreflightCaseSearchResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[_case_read(db, case) for case in cases],
    )


@router.get("/{case_id}", response_model=PreflightCaseRead)
def get_case(
    case_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> PreflightCaseRead:
    return _case_read(db, authorize_case_access(db, user, case_id))


@router.post("/{case_id}/documents", response_model=ProposalDocumentRead, status_code=201)
def upload_document(
    case_id: UUID,
    file: Annotated[UploadFile, File()],
    role: Annotated[ProposalDocumentRole, Form()] = ProposalDocumentRole.PROPOSAL,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> ProposalDocumentRead:
    case = authorize_case_access(db, user, case_id)
    try:
        document = store_proposal_document(
            db,
            case=case,
            filename=file.filename or "",
            content_type=file.content_type,
            role=role,
            source=file.file,
            settings=get_settings(),
        )
    except DuplicateProposalDocumentError as error:
        raise ApiError(409, "DUPLICATE_PROPOSAL_DOCUMENT", str(error)) from error
    except PreflightValidationError as error:
        raise ApiError(422, error.code, error.message) from error
    return ProposalDocumentRead.model_validate(document)


@router.get("/{case_id}/documents/{document_id}/text", response_model=NoticeDocumentTextRead)
def get_document_text(
    case_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> NoticeDocumentTextRead:
    authorize_case_access(db, user, case_id)
    document = _get_document(db, case_id, document_id)
    return NoticeDocumentTextRead(
        document_id=document.id,
        name=document.name,
        extraction_status=document.extraction_status,
        extractor=document.text_extractor,
        char_count=document.extracted_char_count,
        text_sha256=document.extracted_text_sha256,
        text=document.extracted_text,
        blocks=document.extracted_blocks,
    )


@router.get("/{case_id}/documents/{document_id}/source", response_model=None)
def get_document_source(
    case_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> Response:
    authorize_case_access(db, user, case_id)
    return _serve_document(_get_document(db, case_id, document_id), inline=True)


@router.get("/{case_id}/documents/{document_id}/content", response_model=None)
def download_document(
    case_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> Response:
    authorize_case_access(db, user, case_id)
    return _serve_document(_get_document(db, case_id, document_id), inline=False)


@router.get("/{case_id}/documents/{document_id}/preview", response_model=None)
def preview_document(
    case_id: UUID,
    document_id: UUID,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> Response:
    authorize_case_access(db, user, case_id)
    document = _get_document(db, case_id, document_id)
    if document.viewer_type != "PDF":
        raise ApiError(
            409,
            "DOCUMENT_PREVIEW_USE_RHWP",
            "HWP/HWPX 문서는 render_source_url을 rhwp 뷰어로 렌더링해야 합니다.",
        )
    return _serve_document(document, inline=True)
