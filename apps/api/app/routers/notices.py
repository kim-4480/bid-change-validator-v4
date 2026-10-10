from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import String, Text, and_, case as sql_case, cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import Session, selectinload

from ..auth import authorize_company_access, get_optional_current_user
from ..auth_models import AppUser
from ..analysis_models import QualificationAnalysisRun
from ..judgment_models import QualificationJudgmentRun
from ..config import get_settings
from ..database import get_db
from ..errors import ApiError
from ..models import (
    BidNotice,
    BidNoticeVersion,
    NoticeCollectionRun,
    NoticeChangeHistory,
    NoticeDocument,
    NoticeFact,
    NoticeRelation,
    PreflightCase,
)
from ..schemas import (
    BidNoticeDetail,
    BidNoticeSearchResponse,
    BidNoticeSummary,
    BidNoticeVersionRead,
    BusinessType,
    DocumentExtractionBatchRead,
    NoticeCollectionRunRead,
    NoticeChangeHistoryRead,
    NoticeDocumentTextRead,
    NoticeFactDiffRead,
    NoticeFactRead,
    NoticeRelationRead,
    NoticeSyncRequest,
)
from ..services.g2b import G2BApiError, G2BClient
from ..services.document_storage import build_document_downloader, build_s3_client
from ..services.document_reprocessing import extract_pending_documents
from ..services.notices import run_notice_sync
from ..services.notice_facts import diff_notice_facts
from bidengine.judgment.rules import RULE_VERSION


router = APIRouter(prefix="/api/v1/notices", tags=["bid notices"])


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_SEARCH_FIELDS = (
    BidNotice.bid_notice_no,
    BidNotice.title,
    BidNotice.announcing_institution_name,
    BidNotice.demanding_institution_name,
)


def _keyword_filters(query: str) -> list:
    """검색어를 낱말로 나눠 낱말마다 공고번호·공고명·공고기관·수요기관 중 하나에 들어 있어야 한다(낱말끼리 AND).

    예전에는 검색어 전체를 한 덩어리로 부분 일치시켜 '구미 교복', '공주 해체' 처럼 낱말을 둘 넣거나 '건축물해체'
    처럼 띄어쓰기가 제목과 다르면 하나도 잡히지 않았다(2026-10-07). 비교는 양쪽 띄어쓰기를 지우고 한다.
    """
    filters = []
    for token in dict.fromkeys(query.split()):
        pattern = f"%{_escape_like(token)}%"
        filters.append(or_(*(
            func.replace(func.coalesce(field, ""), " ", "").ilike(pattern, escape="\\") for field in _SEARCH_FIELDS
        )))
    return filters


def _summary(
    notice: BidNotice,
    version: BidNoticeVersion,
    *,
    qualification_status: str | None = None,
    current_case_id: UUID | None = None,
) -> BidNoticeSummary:
    return BidNoticeSummary(
        qualification_status=qualification_status,
        current_case_id=current_case_id,
        id=notice.id,
        bid_notice_no=notice.bid_notice_no,
        title=notice.title,
        business_type=notice.business_type,
        notice_kind=notice.notice_kind,
        announcing_institution_code=notice.announcing_institution_code,
        announcing_institution_name=notice.announcing_institution_name,
        demanding_institution_code=notice.demanding_institution_code,
        demanding_institution_name=notice.demanding_institution_name,
        first_seen_at=notice.first_seen_at,
        last_seen_at=notice.last_seen_at,
        current_version=version.version_number,
    )


def _availability_order(now: datetime):
    """Prioritize open notices without hiding expired history or guessing unknown dates."""
    kind = func.lower(func.coalesce(BidNoticeVersion.notice_kind, BidNotice.notice_kind, ""))
    not_cancelled = ~or_(kind.like("%취소%"), kind.like("%cancel%"), kind.like("%무효%"))
    return sql_case(
        (and_(not_cancelled, BidNoticeVersion.bid_closed_at > now), 0),
        (and_(
            not_cancelled,
            BidNoticeVersion.bid_closed_at.is_(None),
            BidNoticeVersion.posted_at.is_not(None),
            BidNoticeVersion.posted_at <= now,
            BidNoticeVersion.posted_at > now - timedelta(days=40),
        ), 1),
        else_=2,
    )


def _render_content_type(document: NoticeDocument) -> str:
    name = document.name.lower()
    if document.content_type == "application/pdf" or name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith(".hwpx") or document.text_extractor == "HWPX_XML":
        return "application/hwp+zip"
    if name.endswith(".hwp") or document.text_extractor == "HWP5_BODYTEXT":
        return "application/x-hwp"
    return document.content_type or "application/octet-stream"


@router.post("/sync", response_model=NoticeCollectionRunRead)
def sync_notices(
    payload: NoticeSyncRequest,
    db: Session = Depends(get_db),
) -> NoticeCollectionRunRead:
    settings = get_settings()
    service_key = settings.decoded_g2b_service_key
    if service_key is None:
        raise ApiError(
            503,
            "G2B_SERVICE_KEY_NOT_CONFIGURED",
            "G2B_SERVICE_KEY가 설정되지 않았습니다.",
        )
    client = G2BClient(
        service_key=service_key,
        base_url=settings.g2b_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
    )
    try:
        document_downloader = build_document_downloader(settings)
        run = run_notice_sync(
            db,
            request=payload,
            client=client,
            document_downloader=document_downloader,
        )
    except G2BApiError as error:
        raise ApiError(
            502,
            "G2B_API_ERROR",
            "나라장터 공고 수집에 실패했습니다.",
            {"upstream_code": error.code, "upstream_message": error.message},
        ) from error
    except ValueError as error:
        raise ApiError(
            502,
            "G2B_DATA_ERROR",
            "나라장터 공고 데이터 형식이 올바르지 않습니다.",
            {"reason": str(error)},
        ) from error
    return NoticeCollectionRunRead.model_validate(run)


@router.get("/collection-runs", response_model=list[NoticeCollectionRunRead])
def list_collection_runs(
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    db: Session = Depends(get_db),
) -> list[NoticeCollectionRunRead]:
    rows = db.scalars(
        select(NoticeCollectionRun)
        .order_by(NoticeCollectionRun.started_at.desc())
        .limit(limit)
    ).all()
    return [NoticeCollectionRunRead.model_validate(row) for row in rows]


def _company_notice_status(company_id: UUID):
    """Correlated scalar lookups: the final status applies BEFORE limit/offset.

    Only a judgment tied to the newest analysis of the CURRENT version and
    matching the rule version counts. Older cases without a current judgment
    are needs_review rather than being mistaken for never reviewed.
    """
    # Recompute the same canonical document lineage as
    # qualification_analysis_document_fingerprint in PostgreSQL. Status filters
    # and pagination happen in SQL, so checking staleness after LIMIT would
    # miscount and could expose an obsolete core_met badge.
    document_json = func.concat(
        literal('{"document_id":"'), cast(NoticeDocument.id, Text),
        literal('","extracted_text_sha256":'),
        sql_case(
            (NoticeDocument.extracted_text_sha256.is_(None), literal("null")),
            else_=func.concat(literal('"'), NoticeDocument.extracted_text_sha256, literal('"')),
        ),
        literal("}"),
    )
    document_rows = (
        select(func.coalesce(func.string_agg(
            document_json,
            aggregate_order_by(literal(","), cast(NoticeDocument.id, String)),
        ), literal("")))
        .where(
            NoticeDocument.notice_version_id == BidNoticeVersion.id,
            NoticeDocument.extraction_status == "EXTRACTED",
            NoticeDocument.extracted_blocks.is_not(None),
            func.jsonb_array_length(NoticeDocument.extracted_blocks) > 0,
        )
        .correlate(BidNoticeVersion)
        .scalar_subquery()
    )
    fingerprint = func.encode(func.sha256(func.convert_to(func.concat(
        literal("qualification-analysis-input-v1\n["), document_rows, literal("]")
    ), literal("UTF8"))), literal("hex"))
    latest_analysis = (
        select(QualificationAnalysisRun.id)
        .where(
            QualificationAnalysisRun.notice_version_id == BidNoticeVersion.id,
            QualificationAnalysisRun.status != "FAILED",
            QualificationAnalysisRun.input_fingerprint == fingerprint,
        )
        .order_by(QualificationAnalysisRun.created_at.desc(), QualificationAnalysisRun.id.desc())
        .limit(1)
        .correlate(BidNoticeVersion)
        .scalar_subquery()
    )
    # FAILED newest analyses must invalidate older judgments, too.
    newest_analysis = (
        select(QualificationAnalysisRun.id)
        .where(QualificationAnalysisRun.notice_version_id == BidNoticeVersion.id)
        .order_by(QualificationAnalysisRun.created_at.desc(), QualificationAnalysisRun.id.desc())
        .limit(1)
        .correlate(BidNoticeVersion)
        .scalar_subquery()
    )
    latest_case = (
        select(PreflightCase.id)
        .where(
            PreflightCase.notice_id == BidNotice.id,
            PreflightCase.current_version_id == BidNoticeVersion.id,
            PreflightCase.company_id == company_id,
        )
        .order_by(PreflightCase.created_at.desc(), PreflightCase.id.desc())
        .limit(1)
        .correlate(BidNotice, BidNoticeVersion)
        .scalar_subquery()
    )
    any_case = exists(
        select(PreflightCase.id)
        .where(
            PreflightCase.notice_id == BidNotice.id,
            PreflightCase.company_id == company_id,
        )
        .correlate(BidNotice)
    )
    valid_judgment_query = (
        select(QualificationJudgmentRun.overall_status, QualificationJudgmentRun.preflight_case_id)
        .join(PreflightCase, PreflightCase.id == QualificationJudgmentRun.preflight_case_id)
        .where(
            QualificationJudgmentRun.company_id == company_id,
            PreflightCase.company_id == company_id,
            PreflightCase.notice_id == BidNotice.id,
            PreflightCase.current_version_id == BidNoticeVersion.id,
            QualificationJudgmentRun.notice_version_id == BidNoticeVersion.id,
            QualificationJudgmentRun.analysis_run_id == newest_analysis,
            QualificationJudgmentRun.analysis_run_id == latest_analysis,
            QualificationJudgmentRun.rule_version == RULE_VERSION,
        )
        .order_by(QualificationJudgmentRun.created_at.desc(), QualificationJudgmentRun.id.desc())
        .limit(1)
        .correlate(BidNotice, BidNoticeVersion)
    )
    valid_judgment = valid_judgment_query.with_only_columns(
        QualificationJudgmentRun.overall_status
    ).scalar_subquery()
    valid_case = valid_judgment_query.with_only_columns(
        QualificationJudgmentRun.preflight_case_id
    ).scalar_subquery()
    status = sql_case(
        (valid_judgment.is_not(None), valid_judgment),
        (any_case, "needs_review"),
        else_="unreviewed",
    )
    # Show the case owning the effective valid judgment when duplicates exist.
    return status, func.coalesce(valid_case, latest_case)


@router.get("", response_model=BidNoticeSearchResponse)
def search_notices(
    q: Annotated[str | None, Query(max_length=200)] = None,
    business_type: BusinessType | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    company_id: UUID | None = None,
    qualification_status: Annotated[
        str | None, Query(pattern="^(core_met|core_unmet|unreviewed|needs_review)$")
    ] = None,
    db: Session = Depends(get_db),
    user: AppUser | None = Depends(get_optional_current_user),
) -> BidNoticeSearchResponse:
    normalized_query = q.strip() if q is not None else None
    if normalized_query == "":
        normalized_query = None

    if company_id is not None:
        authorize_company_access(user, company_id)
    if qualification_status is not None and company_id is None:
        raise ApiError(422, "COMPANY_ID_REQUIRED", "Company ID is required for status filters.")

    filters = []
    if business_type is not None:
        filters.append(BidNotice.business_type == business_type.value)
    if normalized_query is not None:
        filters.extend(_keyword_filters(normalized_query))

    base = (
        select(BidNotice, BidNoticeVersion)
        .join(
            BidNoticeVersion,
            (BidNoticeVersion.notice_id == BidNotice.id)
            & BidNoticeVersion.is_current.is_(True),
        )
        .where(*filters)
    )
    availability_order = _availability_order(datetime.now(timezone.utc))

    if company_id is None:
        total = db.scalar(select(func.count()).select_from(base.with_only_columns(BidNotice.id).order_by(None).subquery())) or 0
        rows = db.execute(
            base.order_by(availability_order, BidNotice.last_seen_at.desc(), BidNotice.id.desc())
            .offset(offset).limit(limit)
        ).all()
        return BidNoticeSearchResponse(
            query=normalized_query, business_type=business_type, total=total,
            limit=limit, offset=offset,
            items=[_summary(notice, version) for notice, version in rows],
        )

    status_expr, case_id_expr = _company_notice_status(company_id)
    # Group and paginate the SAME database-side status classification.
    status_rows = base.with_only_columns(
        BidNotice.id.label("notice_id"),
        status_expr.label("qualification_status"),
    ).subquery()
    counts = dict(
        db.execute(
            select(status_rows.c.qualification_status, func.count())
            .group_by(status_rows.c.qualification_status)
        ).all()
    )
    status_counts = {
        key: counts.get(key, 0)
        for key in ("core_met", "core_unmet", "unreviewed", "needs_review")
    }
    total = sum(status_counts.values()) if qualification_status is None else status_counts[qualification_status]

    page_query = base.add_columns(status_expr.label("qualification_status"), case_id_expr.label("current_case_id"))
    if qualification_status is not None:
        page_query = page_query.where(status_expr == qualification_status)
    rows = db.execute(
        page_query.order_by(availability_order, BidNotice.last_seen_at.desc(), BidNotice.id.desc())
        .offset(offset).limit(limit)
    ).all()
    return BidNoticeSearchResponse(
        query=normalized_query, business_type=business_type, total=total,
        limit=limit, offset=offset, status_counts=status_counts,
        items=[
            _summary(notice, version, qualification_status=status, current_case_id=case_id)
            for notice, version, status, case_id in rows
        ],
    )


@router.post(
    "/documents/extract-pending",
    response_model=DocumentExtractionBatchRead,
)
def extract_pending_notice_documents(
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    retry_failed: bool = False,
    db: Session = Depends(get_db),
) -> DocumentExtractionBatchRead:
    result = extract_pending_documents(
        db,
        settings=get_settings(),
        limit=limit,
        retry_failed=retry_failed,
    )
    return DocumentExtractionBatchRead(**result)


@router.get(
    "/{notice_id}/versions/{version_number}/documents/{document_id}/text",
    response_model=NoticeDocumentTextRead,
)
def get_notice_document_text(
    notice_id: UUID,
    version_number: int,
    document_id: UUID,
    db: Session = Depends(get_db),
) -> NoticeDocumentTextRead:
    document = db.scalar(
        select(NoticeDocument)
        .join(BidNoticeVersion, BidNoticeVersion.id == NoticeDocument.notice_version_id)
        .where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
            NoticeDocument.id == document_id,
        )
    )
    if document is None:
        raise ApiError(404, "NOTICE_DOCUMENT_NOT_FOUND", "공고 첨부파일을 찾을 수 없습니다.")
    return NoticeDocumentTextRead(
        document_id=document.id,
        name=document.name,
        extraction_status=document.extraction_status,
        # Preserved historical extraction bytes are not current evidence.
        extractor=document.text_extractor if document.extraction_status == "EXTRACTED" else None,
        char_count=document.extracted_char_count if document.extraction_status == "EXTRACTED" else None,
        text_sha256=document.extracted_text_sha256 if document.extraction_status == "EXTRACTED" else None,
        text=document.extracted_text if document.extraction_status == "EXTRACTED" else None,
        blocks=document.extracted_blocks if document.extraction_status == "EXTRACTED" else None,
    )


@router.get(
    "/{notice_id}/versions/{version_number}/documents/{document_id}/source",
    response_model=None,
)
def get_notice_document_render_source(
    notice_id: UUID,
    version_number: int,
    document_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    document = db.scalar(
        select(NoticeDocument)
        .join(BidNoticeVersion, BidNoticeVersion.id == NoticeDocument.notice_version_id)
        .where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
            NoticeDocument.id == document_id,
        )
    )
    if document is None:
        raise ApiError(404, "NOTICE_DOCUMENT_NOT_FOUND", "공고 첨부파일을 찾을 수 없습니다.")
    if document.download_status != "DOWNLOADED" or document.storage_key is None:
        raise ApiError(409, "NOTICE_DOCUMENT_NOT_AVAILABLE", "렌더링할 원본 파일이 없습니다.")

    settings = get_settings()
    media_type = _render_content_type(document)
    backend = settings.document_storage_backend.strip().upper()
    if backend == "LOCAL":
        root = Path(settings.document_storage_path).resolve()
        target = (root / document.storage_key).resolve()
        if root not in target.parents or not target.is_file():
            raise ApiError(404, "NOTICE_DOCUMENT_FILE_MISSING", "저장된 첨부파일이 없습니다.")
        return FileResponse(target, media_type=media_type)
    if backend == "S3":
        if not settings.document_s3_bucket:
            raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "S3 저장소 설정이 없습니다.")
        s3 = build_s3_client(
            region=settings.aws_region,
            endpoint_url=settings.document_s3_endpoint_url,
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.document_s3_bucket,
                "Key": document.storage_key,
                "ResponseContentType": media_type,
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=300,
        )
        return RedirectResponse(url, status_code=307)
    raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "첨부파일 저장소 설정이 잘못되었습니다.")


@router.get(
    "/{notice_id}/versions/{version_number}/documents/{document_id}/content",
    response_model=None,
)
def download_notice_document(
    notice_id: UUID,
    version_number: int,
    document_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    document = db.scalar(
        select(NoticeDocument)
        .join(BidNoticeVersion, BidNoticeVersion.id == NoticeDocument.notice_version_id)
        .where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
            NoticeDocument.id == document_id,
        )
    )
    if document is None:
        raise ApiError(404, "NOTICE_DOCUMENT_NOT_FOUND", "공고 첨부파일을 찾을 수 없습니다.")
    if document.download_status != "DOWNLOADED" or document.storage_key is None:
        raise ApiError(
            409,
            "NOTICE_DOCUMENT_NOT_AVAILABLE",
            "첨부파일이 아직 저장되지 않았거나 다운로드에 실패했습니다.",
            {"download_status": document.download_status},
        )

    settings = get_settings()
    backend = settings.document_storage_backend.strip().upper()
    if backend == "LOCAL":
        root = Path(settings.document_storage_path).resolve()
        target = (root / document.storage_key).resolve()
        if root not in target.parents or not target.is_file():
            raise ApiError(404, "NOTICE_DOCUMENT_FILE_MISSING", "저장된 첨부파일이 없습니다.")
        return FileResponse(
            target,
            filename=document.name,
            media_type=document.content_type or "application/octet-stream",
        )
    if backend == "S3":
        if not settings.document_s3_bucket:
            raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "S3 저장소 설정이 없습니다.")
        s3 = build_s3_client(
            region=settings.aws_region,
            endpoint_url=settings.document_s3_endpoint_url,
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.document_s3_bucket, "Key": document.storage_key},
            ExpiresIn=300,
        )
        return RedirectResponse(url, status_code=307)
    raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "첨부파일 저장소 설정이 잘못되었습니다.")


@router.get(
    "/{notice_id}/versions/{version_number}/documents/{document_id}/preview",
    response_model=None,
)
def preview_notice_document(
    notice_id: UUID,
    version_number: int,
    document_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    document = db.scalar(
        select(NoticeDocument)
        .join(BidNoticeVersion, BidNoticeVersion.id == NoticeDocument.notice_version_id)
        .where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
            NoticeDocument.id == document_id,
        )
    )
    if document is None:
        raise ApiError(404, "NOTICE_DOCUMENT_NOT_FOUND", "공고 첨부파일을 찾을 수 없습니다.")
    is_pdf = document.name.lower().endswith(".pdf") or document.content_type == "application/pdf"
    if not is_pdf:
        raise ApiError(
            409,
            "DOCUMENT_PREVIEW_CONVERSION_REQUIRED",
            "HWP/HWPX 원본은 브라우저 미리보기를 위해 PDF 변환이 필요합니다.",
            {"content_type": document.content_type, "name": document.name},
        )
    if document.download_status != "DOWNLOADED" or document.storage_key is None:
        raise ApiError(409, "NOTICE_DOCUMENT_NOT_AVAILABLE", "미리보기 원본이 없습니다.")

    settings = get_settings()
    backend = settings.document_storage_backend.strip().upper()
    if backend == "LOCAL":
        root = Path(settings.document_storage_path).resolve()
        target = (root / document.storage_key).resolve()
        if root not in target.parents or not target.is_file():
            raise ApiError(404, "NOTICE_DOCUMENT_FILE_MISSING", "저장된 첨부파일이 없습니다.")
        return FileResponse(target, media_type="application/pdf")
    if backend == "S3":
        if not settings.document_s3_bucket:
            raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "S3 저장소 설정이 없습니다.")
        s3 = build_s3_client(
            region=settings.aws_region,
            endpoint_url=settings.document_s3_endpoint_url,
        )
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.document_s3_bucket,
                "Key": document.storage_key,
                "ResponseContentType": "application/pdf",
                "ResponseContentDisposition": "inline",
            },
            ExpiresIn=300,
        )
        return RedirectResponse(url, status_code=307)
    raise ApiError(503, "DOCUMENT_STORAGE_NOT_CONFIGURED", "첨부파일 저장소 설정이 잘못되었습니다.")


@router.get("/{notice_id}", response_model=BidNoticeDetail)
def get_notice(
    notice_id: UUID,
    db: Session = Depends(get_db),
) -> BidNoticeDetail:
    row = db.execute(
        select(BidNotice, BidNoticeVersion)
        .join(
            BidNoticeVersion,
            (BidNoticeVersion.notice_id == BidNotice.id)
            & BidNoticeVersion.is_current.is_(True),
        )
        .options(selectinload(BidNoticeVersion.documents))
        .where(BidNotice.id == notice_id)
    ).one_or_none()
    if row is None:
        raise ApiError(404, "NOTICE_NOT_FOUND", "입찰공고를 찾을 수 없습니다.")
    notice, version = row
    summary = _summary(notice, version)
    relation = db.get(NoticeRelation, notice.id)
    relation_read = None
    if relation is not None:
        previous_notice = (
            db.get(BidNotice, relation.previous_notice_id)
            if relation.previous_notice_id is not None
            else None
        )
        relation_read = NoticeRelationRead(
            notice_id=relation.notice_id,
            previous_notice_id=relation.previous_notice_id,
            previous_bid_notice_no=relation.previous_bid_notice_no,
            previous_notice_title=previous_notice.title if previous_notice is not None else None,
            match_method=relation.match_method,
            match_confidence=relation.match_confidence,
            resolved=relation.previous_notice_id is not None,
            created_at=relation.created_at,
            updated_at=relation.updated_at,
        )
    return BidNoticeDetail(
        **summary.model_dump(),
        latest=BidNoticeVersionRead.model_validate(version),
        relation=relation_read,
    )


@router.get("/{notice_id}/versions", response_model=list[BidNoticeVersionRead])
def list_notice_versions(
    notice_id: UUID,
    db: Session = Depends(get_db),
) -> list[BidNoticeVersionRead]:
    if db.get(BidNotice, notice_id) is None:
        raise ApiError(404, "NOTICE_NOT_FOUND", "입찰공고를 찾을 수 없습니다.")
    versions = db.scalars(
        select(BidNoticeVersion)
        .options(selectinload(BidNoticeVersion.documents))
        .where(BidNoticeVersion.notice_id == notice_id)
        .order_by(BidNoticeVersion.version_number.desc())
    ).all()
    return [BidNoticeVersionRead.model_validate(version) for version in versions]


@router.get(
    "/{notice_id}/versions/{version_number}/facts",
    response_model=list[NoticeFactRead],
)
def list_notice_facts(
    notice_id: UUID,
    version_number: int,
    db: Session = Depends(get_db),
) -> list[NoticeFactRead]:
    version = db.scalar(
        select(BidNoticeVersion).where(
            BidNoticeVersion.notice_id == notice_id,
            BidNoticeVersion.version_number == version_number,
        )
    )
    if version is None:
        raise ApiError(404, "NOTICE_VERSION_NOT_FOUND", "입찰공고 버전을 찾을 수 없습니다.")
    facts = db.scalars(
        select(NoticeFact)
        .where(NoticeFact.notice_version_id == version.id)
        .order_by(NoticeFact.fact_key)
    ).all()
    return [NoticeFactRead.model_validate(fact) for fact in facts]


@router.get(
    "/{notice_id}/change-history",
    response_model=list[NoticeChangeHistoryRead],
)
def list_notice_change_history(
    notice_id: UUID,
    version_number: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> list[NoticeChangeHistoryRead]:
    if db.get(BidNotice, notice_id) is None:
        raise ApiError(404, "NOTICE_NOT_FOUND", "입찰공고를 찾을 수 없습니다.")

    query = select(NoticeChangeHistory).where(
        NoticeChangeHistory.notice_id == notice_id
    )
    if version_number is not None:
        version = db.scalar(
            select(BidNoticeVersion).where(
                BidNoticeVersion.notice_id == notice_id,
                BidNoticeVersion.version_number == version_number,
            )
        )
        if version is None:
            raise ApiError(404, "NOTICE_VERSION_NOT_FOUND", "입찰공고 버전을 찾을 수 없습니다.")
        query = query.where(NoticeChangeHistory.notice_version_id == version.id)

    rows = db.scalars(
        query.order_by(
            NoticeChangeHistory.changed_at.desc().nullslast(),
            NoticeChangeHistory.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return [NoticeChangeHistoryRead.model_validate(row) for row in rows]


@router.get("/{notice_id}/fact-changes", response_model=NoticeFactDiffRead)
def get_notice_fact_changes(
    notice_id: UUID,
    baseline_version_id: UUID | None = None,
    current_version_id: UUID | None = None,
    include_unchanged: bool = False,
    db: Session = Depends(get_db),
) -> NoticeFactDiffRead:
    notice = db.get(BidNotice, notice_id)
    if notice is None:
        raise ApiError(404, "NOTICE_NOT_FOUND", "입찰공고를 찾을 수 없습니다.")

    if current_version_id is None:
        current = db.scalar(
            select(BidNoticeVersion).where(
                BidNoticeVersion.notice_id == notice_id,
                BidNoticeVersion.is_current.is_(True),
            )
        )
    else:
        current = db.get(BidNoticeVersion, current_version_id)
        if current is not None and current.notice_id != notice_id:
            current = None
    if current is None:
        raise ApiError(404, "CURRENT_NOTICE_VERSION_NOT_FOUND", "현재 공고 버전을 찾을 수 없습니다.")

    relation = db.get(NoticeRelation, notice_id)
    allowed_baseline_notice_ids = {notice_id}
    if relation is not None and relation.previous_notice_id is not None:
        allowed_baseline_notice_ids.add(relation.previous_notice_id)

    if baseline_version_id is not None:
        baseline = db.get(BidNoticeVersion, baseline_version_id)
        if baseline is not None and baseline.notice_id not in allowed_baseline_notice_ids:
            raise ApiError(
                400,
                "BASELINE_NOTICE_VERSION_INVALID",
                "비교 기준 버전은 같은 공고 또는 연결된 직전 공고에 속해야 합니다.",
            )
    else:
        baseline = db.scalar(
            select(BidNoticeVersion)
            .where(
                BidNoticeVersion.notice_id == notice_id,
                BidNoticeVersion.version_number < current.version_number,
            )
            .order_by(BidNoticeVersion.version_number.desc())
            .limit(1)
        )
        if (
            baseline is None
            and relation is not None
            and relation.previous_notice_id is not None
        ):
            baseline = db.scalar(
                select(BidNoticeVersion).where(
                    BidNoticeVersion.notice_id == relation.previous_notice_id,
                    BidNoticeVersion.is_current.is_(True),
                )
            )
    if baseline is None:
        raise ApiError(404, "BASELINE_NOTICE_VERSION_NOT_FOUND", "비교 기준 공고 버전을 찾을 수 없습니다.")

    baseline_facts = db.scalars(
        select(NoticeFact).where(NoticeFact.notice_version_id == baseline.id)
    ).all()
    current_facts = db.scalars(
        select(NoticeFact).where(NoticeFact.notice_version_id == current.id)
    ).all()
    return NoticeFactDiffRead(
        baseline_version_id=baseline.id,
        current_version_id=current.id,
        changes=diff_notice_facts(
            list(baseline_facts),
            list(current_facts),
            include_unchanged=include_unchanged,
        ),
    )
