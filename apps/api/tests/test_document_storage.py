from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from apps.api.app.services.document_storage import (
    NoticeDocumentDownloader,
    S3DocumentStorage,
    build_s3_client,
)


def test_s3_client_uses_compatible_endpoint() -> None:
    with patch("boto3.client") as client:
        build_s3_client(
            region="ap-osaka-1",
            endpoint_url="https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com/",
        )

    args, kwargs = client.call_args
    assert args == ("s3",)
    assert kwargs["region_name"] == "ap-osaka-1"
    assert kwargs["endpoint_url"] == "https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com"
    assert kwargs["config"].signature_version == "s3v4"
    assert kwargs["config"].s3["addressing_style"] == "path"
    assert kwargs["config"].s3["payload_signing_enabled"] is False
    assert kwargs["config"].request_checksum_calculation == "when_required"
    assert kwargs["config"].response_checksum_validation == "when_required"


def test_s3_storage_passes_endpoint_to_client() -> None:
    with patch("boto3.client") as client:
        S3DocumentStorage(
            "bidcheck-notice-documents",
            "ap-osaka-1",
            "https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com",
        )

    args, kwargs = client.call_args
    assert args == ("s3",)
    assert kwargs["region_name"] == "ap-osaka-1"
    assert kwargs["endpoint_url"] == "https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com"


def test_s3_storage_uses_put_object_with_known_length_body() -> None:
    with patch("boto3.client") as client_factory:
        client = client_factory.return_value
        storage = S3DocumentStorage(
            "bucket",
            "ap-osaka-1",
            "https://namespace.compat.objectstorage.ap-osaka-1.oraclecloud.com",
        )
        storage.put("docs/a.pdf", BytesIO(b"payload"), "application/pdf")

    client.put_object.assert_called_once_with(
        Bucket="bucket",
        Key="docs/a.pdf",
        Body=b"payload",
        ContentType="application/pdf",
    )


@pytest.mark.parametrize(
    "error",
    [
        ClientError({"Error": {"Code": "AccessDenied", "Message": "credential-secret"}}, "PutObject"),
        EndpointConnectionError(endpoint_url="https://example.invalid"),
    ],
)
def test_s3_upload_failure_marks_only_document_failed_without_leaking_details(error) -> None:
    class Response:
        headers = {"Content-Type": "application/pdf"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            del chunk_size
            yield b"%PDF-1.4"

    document = SimpleNamespace(
        url="https://example.invalid/document.pdf",
        name="document.pdf",
        document_order=1,
        source_field="ntceSpecDocUrl1",
        storage_key=None,
        download_status="PENDING",
        download_error=None,
    )
    with patch("requests.Session") as session, patch("boto3.client"), patch.object(
        S3DocumentStorage, "put", side_effect=error
    ):
        session.return_value.get.return_value = Response()
        downloader = NoticeDocumentDownloader(
            storage=S3DocumentStorage("bucket", "ap-northeast-2"),
            storage_prefix="notice-documents",
            timeout_seconds=1,
            max_file_size_bytes=1024,
        )
        downloader.download(document, notice_no="R26BK00000000", version_number=1)

    assert document.download_status == "FAILED"
    assert document.storage_key is None
    assert document.download_error == f"파일 다운로드 실패 ({type(error).__name__})"
    assert "credential-secret" not in document.download_error
