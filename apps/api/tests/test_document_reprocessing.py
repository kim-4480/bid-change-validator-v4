"""Fail-closed tests for attachment storage and extractor integration.

No network calls, production databases, or storage writes are involved.
"""
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.api.app.services import document_reprocessing as svc


def settings(tmp_path, backend="LOCAL"):
    return SimpleNamespace(
        document_storage_backend=backend,
        document_storage_path=str(tmp_path),
        document_max_file_size_bytes=1024 * 1024,
        document_s3_bucket="isolated-test-bucket",
        aws_region="ap-osaka-1",
        document_s3_endpoint_url=None,
    )


def document(key="v1/a.txt", expected=None, size=None, status="PENDING"):
    return SimpleNamespace(
        storage_key=key,
        name="a.txt",
        content_type="text/plain",
        file_sha256=expected,
        file_size_bytes=size,
        download_status="DOWNLOADED",
        extraction_status=status,
        extracted_text="STALE",
        extracted_blocks=[{"text": "STALE"}],
        extracted_text_sha256=hashlib.sha256(b"STALE").hexdigest(),
        extracted_char_count=5,
        text_extractor="PREVIOUS",
        extracted_at=None,
        extraction_error="OLD_ERROR",
    )


def test_legacy_document_backfills_hash_only_after_verification(tmp_path):
    target = tmp_path / "v1" / "a.txt"
    target.parent.mkdir()
    target.write_bytes(b"hello original")
    record = document()
    svc.process_document(record, settings=settings(tmp_path))
    assert record.extraction_status == "EXTRACTED"
    assert record.extracted_text == "hello original"
    assert record.file_sha256 == hashlib.sha256(b"hello original").hexdigest()
    assert record.extracted_text_sha256 == hashlib.sha256(b"hello original").hexdigest()
    assert record.extracted_char_count == 14
    assert record.file_size_bytes == 14
    assert record.extraction_error is None


@pytest.mark.parametrize(
    ("key", "failure"),
    [
        ("v1/missing.txt", "SOURCE_MISSING"),
        ("../outside.txt", "INVALID_STORAGE_KEY"),
    ],
)
def test_missing_or_traversing_storage_key_fails_closed(tmp_path, key, failure):
    record = document(key=key)
    svc.process_document(record, settings=settings(tmp_path))
    assert record.extraction_status == "FAILED"
    assert record.extraction_error == failure
    assert record.extracted_text is None
    assert record.extracted_text_sha256 is None
    assert record.extracted_blocks is None


def test_wrong_original_sha_is_not_silently_rewritten(tmp_path):
    target = tmp_path / "v1" / "a.txt"
    target.parent.mkdir()
    target.write_bytes(b"different source")
    original_expected = "0" * 64
    record = document(expected=original_expected)
    svc.process_document(record, settings=settings(tmp_path))
    assert record.extraction_error == "SOURCE_SHA256_MISMATCH"
    assert record.extraction_status == "FAILED"
    assert record.file_sha256 == original_expected
    assert record.extracted_text is None


def test_original_size_mismatch_prevents_extraction(tmp_path):
    (tmp_path / "x.txt").write_bytes(b"data")
    record = document(key="x.txt", size=123)
    svc.process_document(record, settings=settings(tmp_path))
    assert record.extraction_status == "FAILED"
    assert record.extraction_error == "SOURCE_SIZE_MISMATCH"


def test_local_permission_error_is_not_reported_as_missing(tmp_path, monkeypatch):
    record = document()
    def forbidden_open(self, *args, **kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(svc.Path, "open", forbidden_open)
    svc.process_document(record, settings=settings(tmp_path))
    assert record.extraction_error == "SOURCE_ACCESS_DENIED"
    assert record.extracted_text is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("NoSuchKey", "SOURCE_MISSING"),
        ("AccessDenied", "SOURCE_ACCESS_DENIED"),
        ("SignatureDoesNotMatch", "SOURCE_ACCESS_DENIED"),
        ("500", "SOURCE_READ_FAILED"),
    ],
)
def test_s3_errors_are_classified_without_writes(tmp_path, monkeypatch, code, expected):
    class ObjectError(Exception):
        response = {"Error": {"Code": code}}

    client = Mock()
    client.get_object.side_effect = ObjectError("hidden endpoint")
    monkeypatch.setattr(svc, "build_s3_client", lambda **kwargs: client)
    record = document()
    svc.process_document(record, settings=settings(tmp_path, "S3"))
    assert record.extraction_error == expected
    assert record.extraction_status == "FAILED"
    assert client.get_object.call_count == (2 if code == "500" else 1)
    client.put_object.assert_not_called()
    client.delete_object.assert_not_called()
    client.head_object.assert_not_called()


def test_parser_failure_cannot_leave_previous_success(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"valid")
    record = document(key="a.txt", status="FAILED")
    def broken_parser(*args, **kwargs):
        raise RuntimeError("parser crashed")
    monkeypatch.setattr(svc, "extract_into_document", broken_parser)
    svc.process_document(record, settings=settings(tmp_path))
    assert record.extraction_status == "FAILED"
    assert record.extracted_text is None
    assert record.extracted_blocks is None
    assert record.extracted_text_sha256 is None


def test_duplicate_key_with_different_expected_digest_is_not_reused(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"shared")
    digest = hashlib.sha256(b"shared").hexdigest()
    first = document(key="a.txt", expected=digest)
    second = document(key="a.txt", expected="f" * 64)
    class FakeSession:
        def __init__(self):
            self.commit_count = 0
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: [first, second])
        def commit(self):
            self.commit_count += 1
    db = FakeSession()
    counts = svc.extract_pending_documents(db, settings=settings(tmp_path), limit=10)
    assert counts["extracted_count"] == 1
    assert counts["failed_count"] == 1
    assert second.extraction_error == "SOURCE_SHA256_MISMATCH"
    assert db.commit_count == 1


def test_downloaded_files_only_and_retry_behavior(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"recovered")
    record = document(key="a.txt", status="FAILED")
    class FakeSession:
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: [record])
        def commit(self):
            pass
    results = svc.extract_pending_documents(
        FakeSession(), settings=settings(tmp_path), limit=1, retry_failed=True
    )
    assert results["extracted_count"] == 1
    assert record.extraction_status == "EXTRACTED"
    assert record.extraction_error is None



def test_s3_object_key_uses_exact_persisted_prefix(tmp_path):
    config = settings(tmp_path, "S3")
    config.document_s3_prefix = "notice-documents"
    original_key = "notice-documents/notice-123/v0001/stdNtceDocUrl-a.pdf"
    assert svc.s3_object_key(config, original_key) == original_key
    # Unknown legacy paths must be checked exactly before declaring them missing.
    assert svc.s3_object_key(config, "legacy/v0001/a.hwp") == "legacy/v0001/a.hwp"
    with pytest.raises(svc.AttachmentReadError, match="INVALID_STORAGE_KEY"):
        svc.s3_object_key(config, "../notice-documents/secret.txt")


def test_s3_head_metadata_only_uses_single_call(tmp_path, monkeypatch):
    config = settings(tmp_path, "S3")
    client = Mock()
    client.head_object.return_value = {"ContentLength": 42}
    monkeypatch.setattr(svc, "build_s3_client", lambda **kwargs: client)
    key = "notice-documents/one.pdf"
    assert svc.probe_document_source(config, key) == {"status": "PRESENT", "size": 42}
    client.head_object.assert_called_once_with(Bucket=config.document_s3_bucket, Key=key)
    client.get_object.assert_not_called()
    client.put_object.assert_not_called()
    client.delete_object.assert_not_called()


def test_s3_head_403_distinguishable_from_404(tmp_path, monkeypatch):
    class Error(Exception):
        def __init__(self, code):
            self.response = {"Error": {"Code": code}}
    config = settings(tmp_path, "S3")
    client = Mock()
    monkeypatch.setattr(svc, "build_s3_client", lambda **kwargs: client)
    client.head_object.side_effect = Error("AccessDenied")
    assert svc.probe_document_source(config, "notice-documents/a.pdf")["status"] == "SOURCE_ACCESS_DENIED"
    client.head_object.side_effect = Error("404")
    assert svc.probe_document_source(config, "notice-documents/a.pdf")["status"] == "SOURCE_MISSING"
    assert client.head_object.call_count == 2


def test_s3_stream_size_limit_before_read(tmp_path, monkeypatch):
    client = Mock()
    source = Mock()
    client.get_object.return_value = {"Body": source, "ContentLength": 1024 * 1024 + 1}
    monkeypatch.setattr(svc, "build_s3_client", lambda **kwargs: client)
    record = document()
    svc.process_document(record, settings=settings(tmp_path, "S3"))
    assert record.extraction_status == "FAILED"
    assert record.extraction_error == "SOURCE_TOO_LARGE"
    source.read.assert_not_called()
    source.close.assert_called_once()


def test_s3_retries_single_transient_error_and_preserves_bytes(tmp_path, monkeypatch):
    class Retryable(Exception):
        response = {"Error": {"Code": "503"}}
    client = Mock()
    payload = b"hello"
    client.get_object.side_effect = [
        Retryable("brief outage"),
        {"Body": BytesIO(payload), "ContentLength": len(payload)},
    ]
    monkeypatch.setattr(svc, "build_s3_client", lambda **kwargs: client)
    record = document(expected=hashlib.sha256(payload).hexdigest(), size=len(payload))
    svc.process_document(record, settings=settings(tmp_path, "S3"))
    assert record.extraction_status == "EXTRACTED"
    assert record.extracted_text == "hello"
    assert client.get_object.call_count == 2


def test_parser_reported_failure_discards_previous_text(tmp_path, monkeypatch):
    (tmp_path / "a.txt").write_bytes(b"source")
    record = document(key="a.txt")
    def silently_failed(document, source):
        document.extraction_status = "FAILED"
        document.extraction_error = "PdfReadError"
        document.extracted_text = "partial data"
    monkeypatch.setattr(svc, "extract_into_document", silently_failed)
    svc.process_document(record, settings=settings(tmp_path))
    assert record.extraction_status == "FAILED"
    assert record.extraction_error.startswith("PARSER_FAILED:")
    assert record.extracted_text is None
    assert record.extracted_text_sha256 is None


def test_same_key_and_sha_but_different_expected_sizes_cannot_share_cache(tmp_path):
    payload = b"content"
    (tmp_path / "a.txt").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    first = document(key="a.txt", expected=digest, size=len(payload))
    second = document(key="a.txt", expected=digest, size=len(payload) + 1)
    class FakeSession:
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: [first, second])
        def commit(self):
            pass
    counts = svc.extract_pending_documents(FakeSession(), settings=settings(tmp_path), limit=2)
    assert counts["extracted_count"] == 1
    assert counts["failed_count"] == 1
    assert second.extraction_error == "SOURCE_SIZE_MISMATCH"


def test_duplicate_legacy_rows_share_read_and_receive_original_hash(tmp_path, monkeypatch):
    payload = b"single read"
    (tmp_path / "a.txt").write_bytes(payload)
    first = document(key="a.txt")
    second = document(key="a.txt")
    real_parser = svc.extract_into_document
    calls = []
    def counted_parser(document, source):
        calls.append(1)
        return real_parser(document, source)
    monkeypatch.setattr(svc, "extract_into_document", counted_parser)
    class FakeSession:
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: [first, second])
        def commit(self):
            pass
    result = svc.extract_pending_documents(
        FakeSession(), settings=settings(tmp_path), limit=2
    )
    assert result["extracted_count"] == 2
    assert len(calls) == 1
    assert second.file_sha256 == first.file_sha256 == hashlib.sha256(payload).hexdigest()
    assert second.file_size_bytes == first.file_size_bytes == len(payload)


def test_failed_duplicate_avoids_repeated_s3_gets(tmp_path, monkeypatch):
    class NoSuchKey(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}
    client = Mock()
    client.get_object.side_effect = NoSuchKey("missing")
    monkeypatch.setattr(svc, "build_s3_client", lambda **kwargs: client)
    first = document(key="notice-documents/a.pdf")
    second = document(key="notice-documents/a.pdf")
    class FakeSession:
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: [first, second])
        def commit(self):
            pass
    result = svc.extract_pending_documents(
        FakeSession(), settings=settings(tmp_path, "S3"), limit=2
    )
    assert result["failed_count"] == 2
    assert first.extraction_error == second.extraction_error == "SOURCE_MISSING"
    client.get_object.assert_called_once()


def test_s3_sdk_retry_budget_is_one_per_application_attempt():
    from apps.api.app.services.document_storage import build_s3_client
    from unittest.mock import patch
    with patch("boto3.client") as factory:
        build_s3_client(region="ap-northeast-2", total_max_attempts=1)
    options = factory.call_args.kwargs["config"].retries
    assert options["total_max_attempts"] == 1
    with pytest.raises(ValueError, match="total_max_attempts"):
        build_s3_client(region="ap-northeast-2", total_max_attempts=4)


def test_same_object_different_document_format_cannot_reuse_extraction(tmp_path):
    payload = b"plain text"
    (tmp_path / "a.txt").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    first = document(key="a.txt", expected=digest, size=len(payload))
    second = document(key="a.txt", expected=digest, size=len(payload))
    second.name = "actually.pdf"
    class FakeSession:
        def scalars(self, stmt):
            return SimpleNamespace(all=lambda: [first, second])
        def commit(self):
            pass
    result = svc.extract_pending_documents(
        FakeSession(), settings=settings(tmp_path), limit=2
    )
    assert result["extracted_count"] == 1
    assert result["failed_count"] == 1
    assert first.extracted_text == "plain text"
    assert second.extracted_text is None
