"""Verified, read-only attachment reprocessing independent of the PDF/HWP parsers.

The storage backend is read-only. Only the caller's SQLAlchemy transaction is updated.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import NoticeDocument
from .document_extraction import copy_extraction, extract_into_document
from .document_storage import build_s3_client

KST = ZoneInfo("Asia/Seoul")
READ_SIZE = 1024 * 1024
MAX_S3_READ_ATTEMPTS = 2


class AttachmentReadError(Exception):
    """Typed failure that must never be reported as a successful extraction."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def classify_read_error(error: Exception) -> str:
    """Do not equate 403 / network failures with missing objects."""
    if isinstance(error, FileNotFoundError):
        return "SOURCE_MISSING"
    if isinstance(error, PermissionError):
        return "SOURCE_ACCESS_DENIED"
    response = getattr(error, "response", None)
    code = ""
    if isinstance(response, dict):
        code = str(response.get("Error", {}).get("Code", ""))
    if code in {"404", "NoSuchKey", "NotFound"}:
        return "SOURCE_MISSING"
    if code in {"403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"}:
        return "SOURCE_ACCESS_DENIED"
    if code in {"NoSuchBucket", "InvalidBucketName"}:
        return "SOURCE_STORAGE_CONFIGURATION"
    return "SOURCE_READ_FAILED"


def local_document_path(root: str, storage_key: str) -> Path:
    """Resolve symlinks and prevent traversal outside the configured mount."""
    base = Path(root).resolve()
    target = (base / storage_key).resolve()
    if not storage_key or target == base or base not in target.parents:
        raise AttachmentReadError("INVALID_STORAGE_KEY")
    return target


def s3_object_key(settings: Settings, storage_key: str) -> str:
    """The existing writer has ALREADY prefixed keys persisted in the DB.

    Never prepend DOCUMENT_S3_PREFIX twice or guess a new key for unprefixed
    legacy rows; those rows require explicit HEAD-based investigation.
    """
    if (
        not storage_key
        or storage_key.startswith("/")
        or "\\" in storage_key
        or any(part in {"", ".", ".."} for part in storage_key.split("/"))
    ):
        raise AttachmentReadError("INVALID_STORAGE_KEY")
    return storage_key


def probe_document_source(settings: Settings, storage_key: str) -> dict[str, int | str | None]:
    """Opt-in, single-object HEAD/stat check; never downloads object bodies."""
    backend = settings.document_storage_backend.strip().upper()
    try:
        if backend == "LOCAL":
            path = local_document_path(settings.document_storage_path, storage_key)
            return {"status": "PRESENT", "size": path.stat().st_size}
        if backend == "S3":
            if not settings.document_s3_bucket:
                raise ValueError("DOCUMENT_S3_BUCKET is required when backend is S3")
            key = s3_object_key(settings, storage_key)
            client = build_s3_client(
                region=settings.aws_region,
                endpoint_url=settings.document_s3_endpoint_url,
                total_max_attempts=1,
            )
            result = client.head_object(Bucket=settings.document_s3_bucket, Key=key)
            return {"status": "PRESENT", "size": result.get("ContentLength")}
        raise ValueError("DOCUMENT_STORAGE_BACKEND must be LOCAL or S3")
    except AttachmentReadError as error:
        return {"status": error.category, "size": None}
    except Exception as error:
        return {"status": classify_read_error(error), "size": None}


def _transient_s3_error(error: Exception) -> bool:
    response = getattr(error, "response", None)
    code = str(response.get("Error", {}).get("Code", "")) if isinstance(response, dict) else ""
    return (
        code in {"408", "429", "500", "502", "503", "504", "SlowDown", "RequestTimeout", "InternalError"}
        or isinstance(error, TimeoutError)
        or type(error).__name__ in {
            "ConnectTimeoutError", "ReadTimeoutError",
            "EndpointConnectionError", "ConnectionClosedError",
        }
    )


def _read_s3_bounded(client, settings: Settings, key: str, temp: BinaryIO) -> None:
    """One streaming GET per attempt; at most one additional transient retry."""
    for attempt in range(MAX_S3_READ_ATTEMPTS):
        temp.seek(0)
        temp.truncate(0)
        try:
            result = client.get_object(Bucket=settings.document_s3_bucket, Key=key)
            body = result["Body"]
            try:
                length = result.get("ContentLength")
                if length is not None and length > settings.document_max_file_size_bytes:
                    raise AttachmentReadError("SOURCE_TOO_LARGE")
                _copy_bounded(body, temp, settings.document_max_file_size_bytes)
            finally:
                body.close()
            return
        except AttachmentReadError:
            raise
        except Exception as error:
            if not _transient_s3_error(error) or attempt + 1 == MAX_S3_READ_ATTEMPTS:
                raise AttachmentReadError(classify_read_error(error)) from error


@contextmanager
def verified_document_source(
    settings: Settings,
    document: NoticeDocument,
) -> Iterator[tuple[BinaryIO, str, int]]:
    """Read once, check original digest/size, and rewind before parsing.

    Never retries via the public URL: historical versions must be tied to their
    originally downloaded bytes, not a potentially changed remote response.
    """
    key = document.storage_key
    if not key:
        raise AttachmentReadError("SOURCE_MISSING")
    backend = settings.document_storage_backend.strip().upper()
    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temp:
        if backend == "LOCAL":
            source_path = local_document_path(settings.document_storage_path, key)
            try:
                with source_path.open("rb") as source:
                    _copy_bounded(source, temp, settings.document_max_file_size_bytes)
            except OSError as error:
                raise AttachmentReadError(classify_read_error(error)) from error
        elif backend == "S3":
            if not settings.document_s3_bucket:
                raise ValueError("DOCUMENT_S3_BUCKET is required when backend is S3")
            try:
                client = build_s3_client(
                    region=settings.aws_region,
                    endpoint_url=settings.document_s3_endpoint_url,
                    total_max_attempts=1,
                )
                # DB storage_key is already a complete S3 key.
                _read_s3_bounded(client, settings, s3_object_key(settings, key), temp)
            except AttachmentReadError:
                raise
            except Exception as error:
                raise AttachmentReadError(classify_read_error(error)) from error
        else:
            raise ValueError("DOCUMENT_STORAGE_BACKEND must be LOCAL or S3")

        temp.seek(0)
        digest = hashlib.sha256()
        size = 0
        while chunk := temp.read(READ_SIZE):
            size += len(chunk)
            digest.update(chunk)
        actual_sha = digest.hexdigest()
        if document.file_size_bytes is not None and document.file_size_bytes != size:
            raise AttachmentReadError("SOURCE_SIZE_MISMATCH")
        if document.file_sha256 and document.file_sha256.lower() != actual_sha:
            raise AttachmentReadError("SOURCE_SHA256_MISMATCH")
        temp.seek(0)
        yield temp, actual_sha, size


def _copy_bounded(source: BinaryIO, target: BinaryIO, max_bytes: int) -> None:
    size = 0
    while chunk := source.read(READ_SIZE):
        size += len(chunk)
        if size > max_bytes:
            raise AttachmentReadError("SOURCE_TOO_LARGE")
        target.write(chunk)


def _valid_retained_extraction(document: NoticeDocument) -> bool:
    """Only keep a verifiable prior successful payload on an unsuccessful retry.

    It remains *inactive* while extraction_status != EXTRACTED. No new columns,
    no migration, and no false success on S3/parser failures.
    """
    text = document.extracted_text
    blocks = document.extracted_blocks
    if not (
        isinstance(text, str)
        and text
        and isinstance(blocks, list)
        and blocks
        and document.extracted_at is not None
        and bool(document.text_extractor)
        and isinstance(document.file_sha256, str)
        and len(document.file_sha256) == 64
        and all(char in "0123456789abcdefABCDEF" for char in document.file_sha256)
        and isinstance(document.extracted_text_sha256, str)
        and document.extracted_char_count == len(text)
    ):
        return False
    try:
        block_text = "\n\n".join(block["text"] for block in blocks)
        return (
            block_text == text
            and hashlib.sha256(text.encode("utf-8")).hexdigest() == document.extracted_text_sha256
        )
    except (TypeError, KeyError):
        return False


def _invalidate_extraction(
    document: NoticeDocument, *, status: str, reason: str | None
) -> None:
    """Preserve validated historical bytes, but make them non-current."""
    if not _valid_retained_extraction(document):
        _clear_extraction(document)
        document.extracted_at = datetime.now(KST)
    document.extraction_status = status
    document.extraction_error = reason


def _clear_extraction(document: NoticeDocument) -> None:
    document.extracted_text = None
    document.extracted_blocks = None
    document.extracted_char_count = None
    document.extracted_text_sha256 = None
    document.text_extractor = None
    document.extracted_at = None
    document.extraction_error = None
    document.extraction_status = "PENDING"


def process_document(
    document: NoticeDocument,
    *,
    settings: Settings,
) -> None:
    """Publish extraction atomically, without destroying prior evidence on failure.

    EXTRACTED documents are not eligible for the PENDING/FAILED retry pipeline.
    A failed retry leaves verified previous text in storage, but status != EXTRACTED
    ensures analysis and RAG cannot use that text as current evidence.
    """
    if document.extraction_status == "EXTRACTED":
        return

    try:
        with verified_document_source(settings, document) as (source, digest, size):
            if not document.file_sha256:
                document.file_sha256 = digest
            if document.file_size_bytes is None:
                document.file_size_bytes = size

            # Parse into a detached object. Parser failure, EMPTY and UNSUPPORTED
            # must not overwrite an older extract before status is determined.
            candidate = SimpleNamespace(
                name=document.name,
                content_type=document.content_type,
                extraction_status="PENDING",
                extraction_error=None,
            )
            try:
                extract_into_document(candidate, source)
            except Exception:
                raise AttachmentReadError("PARSER_FAILED")

            if candidate.extraction_status == "FAILED":
                details = candidate.extraction_error or ""
                raise AttachmentReadError("PARSER_FAILED:" + details[:180])
            if candidate.extraction_status in {"EMPTY", "UNSUPPORTED"}:
                _invalidate_extraction(
                    document,
                    status=candidate.extraction_status,
                    reason=candidate.extraction_error,
                )
                return
            if candidate.extraction_status != "EXTRACTED":
                raise AttachmentReadError("PARSER_INVALID_STATUS")

            text = candidate.extracted_text
            if not isinstance(text, str) or not text:
                raise AttachmentReadError("EXTRACTED_EMPTY_TEXT")
            actual_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if actual_sha != candidate.extracted_text_sha256:
                raise AttachmentReadError("EXTRACTED_SHA256_MISMATCH")
            if len(text) != candidate.extracted_char_count:
                raise AttachmentReadError("EXTRACTED_LENGTH_MISMATCH")
            if not candidate.extracted_blocks:
                raise AttachmentReadError("EXTRACTED_MISSING_BLOCKS")
            copy_extraction(candidate, document)
    except AttachmentReadError as error:
        _invalidate_extraction(document, status="FAILED", reason=error.category)
    except Exception:
        # Never persist credential-bearing S3 exception messages.
        _invalidate_extraction(document, status="FAILED", reason="SOURCE_READ_FAILED")


def extract_pending_documents(
    db: Session,
    *,
    settings: Settings,
    limit: int,
    retry_failed: bool = False,
) -> dict[str, int]:
    if limit < 1:
        raise ValueError("limit must be positive")
    statuses = ["PENDING", "FAILED"] if retry_failed else ["PENDING"]
    documents = db.scalars(
        select(NoticeDocument)
        .where(
            NoticeDocument.download_status == "DOWNLOADED",
            NoticeDocument.storage_key.is_not(None),
            NoticeDocument.extraction_status.in_(statuses),
        )
        .order_by(NoticeDocument.created_at)
        .limit(limit)
    ).all()
    # Include SHA/size and parser identity: identical bytes named TXT vs PDF
    # can parse differently, so a conflicting record cannot inherit success.
    # Cache FAILED outcomes too, to avoid repeated S3 GETs for one missing key.
    batch_cache: dict[tuple[str, str, int | None, str, str], NoticeDocument] = {}
    counts = {"EXTRACTED": 0, "EMPTY": 0, "UNSUPPORTED": 0, "FAILED": 0}
    for document in documents:
        key = (
            document.storage_key or "", document.file_sha256 or "",
            document.file_size_bytes, document.name, document.content_type or "",
        )
        cached = batch_cache.get(key)
        if cached is not None:
            if cached.extraction_status == "EXTRACTED":
                copy_extraction(cached, document)
            else:
                _invalidate_extraction(
                    document,
                    status=cached.extraction_status,
                    reason=cached.extraction_error,
                )
            # Legacy duplicate rows with missing original metadata must receive
            # the verified hash/size too, not just the extracted text.
            if not document.file_sha256:
                document.file_sha256 = cached.file_sha256
            if document.file_size_bytes is None:
                document.file_size_bytes = cached.file_size_bytes
        else:
            process_document(document, settings=settings)
            batch_cache[key] = document
            batch_cache[(
                document.storage_key or "", document.file_sha256 or "",
                document.file_size_bytes, document.name, document.content_type or "",
            )] = document
        counts[document.extraction_status] = counts.get(document.extraction_status, 0) + 1
    db.commit()
    return {
        "requested_count": len(documents),
        "extracted_count": counts["EXTRACTED"],
        "empty_count": counts["EMPTY"],
        "unsupported_count": counts["UNSUPPORTED"],
        "failed_count": counts["FAILED"],
        # API schema exposes the existing counters; detailed failures are
        # recorded per-document for inspection without changing that contract.
    }
