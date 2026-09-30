import hashlib
import re
import shutil
from datetime import datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Protocol
from zoneinfo import ZoneInfo

import requests

from ..config import Settings
from ..models import NoticeDocument
from .document_extraction import extract_into_document


KST = ZoneInfo("Asia/Seoul")


class DocumentStorage(Protocol):
    def put(self, storage_key: str, source: BinaryIO, content_type: str | None) -> str: ...


def build_s3_client(*, region: str | None, endpoint_url: str | None = None):
    """Build the S3 client used by both storage and signed-download paths.

    ``endpoint_url`` keeps the storage implementation compatible with OCI's
    S3 Compatibility API while remaining optional for AWS S3.
    """
    import boto3
    from botocore.config import Config

    kwargs: dict[str, object] = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url.rstrip("/")
    # OCI's S3 Compatibility API does not accept AWS chunked payload
    # signatures. Disable payload signing and use path-style addressing; both
    # settings are also valid for AWS S3 and keep the client deterministic.
    kwargs["config"] = Config(
        signature_version="s3v4",
        s3={"addressing_style": "path", "payload_signing_enabled": False},
        request_checksum_calculation="when_required",
        response_checksum_validation="when_required",
    )
    return boto3.client("s3", **kwargs)


class LocalDocumentStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, storage_key: str, source: BinaryIO, content_type: str | None) -> str:
        del content_type
        target = (self.root / storage_key).resolve()
        if self.root not in target.parents:
            raise ValueError("invalid document storage key")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.seek(0)
        with target.open("wb") as output:
            shutil.copyfileobj(source, output)
        return storage_key.replace("\\", "/")


class S3DocumentStorage:
    def __init__(self, bucket: str, region: str | None, endpoint_url: str | None = None) -> None:
        self.bucket = bucket
        self.client = build_s3_client(region=region, endpoint_url=endpoint_url)

    def put(self, storage_key: str, source: BinaryIO, content_type: str | None) -> str:
        source.seek(0)
        # ``upload_fileobj`` may use AWS chunked encoding when the stream length
        # is unknown. OCI's S3 Compatibility API rejects that transfer mode, so
        # send a bytes body with a known length instead. The downloader already
        # bounds each document size, and this keeps AWS S3 behavior unchanged.
        params: dict[str, object] = {
            "Bucket": self.bucket,
            "Key": storage_key,
            "Body": source.read(),
        }
        if content_type:
            params["ContentType"] = content_type
        self.client.put_object(**params)
        return storage_key


def safe_storage_segment(value: str, fallback: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value.strip())
    value = value.strip("._")
    return value[:150] or fallback


class NoticeDocumentDownloader:
    def __init__(
        self,
        *,
        storage: DocumentStorage,
        storage_prefix: str,
        timeout_seconds: float,
        max_file_size_bytes: int,
        session: requests.Session | None = None,
    ) -> None:
        self.storage = storage
        self.storage_prefix = storage_prefix.strip("/")
        self.timeout_seconds = timeout_seconds
        self.max_file_size_bytes = max_file_size_bytes
        self.session = session or requests.Session()

    def download(
        self,
        document: NoticeDocument,
        *,
        notice_no: str,
        version_number: int,
        known_storage_by_hash: dict[str, str] | None = None,
        extract_document: bool = True,
    ) -> None:
        try:
            with self.session.get(
                document.url,
                stream=True,
                timeout=self.timeout_seconds,
                allow_redirects=True,
                headers={"User-Agent": "bid-change-validator/0.1"},
            ) as response:
                response.raise_for_status()
                declared_size = int(response.headers.get("Content-Length") or 0)
                if declared_size > self.max_file_size_bytes:
                    raise ValueError("file exceeds configured size limit")

                sha256 = hashlib.sha256()
                size = 0
                with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temp:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        size += len(chunk)
                        if size > self.max_file_size_bytes:
                            raise ValueError("file exceeds configured size limit")
                        sha256.update(chunk)
                        temp.write(chunk)

                    notice_segment = safe_storage_segment(notice_no, "unknown-notice")
                    name_segment = safe_storage_segment(document.name, f"document-{document.document_order}")
                    parts = [
                        notice_segment,
                        f"v{version_number:04d}",
                        f"{document.source_field}-{name_segment}",
                    ]
                    storage_key = "/".join(parts)
                    if self.storage_prefix:
                        storage_key = f"{self.storage_prefix}/{storage_key}"
                    digest = sha256.hexdigest()
                    existing_storage_key = (known_storage_by_hash or {}).get(digest)
                    if existing_storage_key is not None:
                        document.storage_key = existing_storage_key
                    else:
                        document.storage_key = self.storage.put(
                            storage_key,
                            temp,
                            response.headers.get("Content-Type"),
                        )
                        if known_storage_by_hash is not None:
                            known_storage_by_hash[digest] = document.storage_key
                    document.content_type = response.headers.get("Content-Type")
                    document.file_size_bytes = size
                    document.file_sha256 = digest
                    document.downloaded_at = datetime.now(KST)
                    document.download_status = "DOWNLOADED"
                    document.download_error = None
                    if extract_document:
                        extract_into_document(document, temp)
        except (requests.RequestException, OSError, ValueError) as error:
            document.download_status = "FAILED"
            document.download_error = (
                f"파일 다운로드 실패 ({type(error).__name__})"
            )


def build_document_downloader(settings: Settings) -> NoticeDocumentDownloader:
    storage, prefix = build_document_storage(settings)
    return NoticeDocumentDownloader(
        storage=storage,
        storage_prefix=prefix,
        timeout_seconds=settings.document_download_timeout_seconds,
        max_file_size_bytes=settings.document_max_file_size_bytes,
    )


def build_document_storage(settings: Settings) -> tuple[DocumentStorage, str]:
    backend = settings.document_storage_backend.strip().upper()
    if backend == "LOCAL":
        storage: DocumentStorage = LocalDocumentStorage(settings.document_storage_path)
        prefix = ""
    elif backend == "S3":
        if not settings.document_s3_bucket:
            raise ValueError("DOCUMENT_S3_BUCKET is required when backend is S3")
        storage = S3DocumentStorage(
            settings.document_s3_bucket,
            settings.aws_region,
            settings.document_s3_endpoint_url,
        )
        prefix = settings.document_s3_prefix
    else:
        raise ValueError("DOCUMENT_STORAGE_BACKEND must be LOCAL or S3")
    return storage, prefix
