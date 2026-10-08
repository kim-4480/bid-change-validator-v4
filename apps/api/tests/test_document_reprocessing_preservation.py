"""Regression contract: preserve verifiable old extraction without reviving stale analysis.

Uses only temp files and Mock S3. No external AWS/API/DB operations.
"""
import hashlib
import json
from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from apps.api.app.services import document_reprocessing as processing
from apps.api.app.qualification.analysis import build_qualification_analysis_input
from apps.api.app.document_rag.service import build_notice_version_records
from apps.api.app.routers.notices import get_notice_document_text
from apps.api.app.scripts.product_golden_inspector import find_snippets


def settings(tmp_path, backend="LOCAL"):
    return SimpleNamespace(
        document_storage_backend=backend,
        document_storage_path=str(tmp_path),
        document_max_file_size_bytes=1024 * 1024,
        document_s3_bucket="mock-only-bucket",
        aws_region="ap-northeast-2",
        document_s3_endpoint_url=None,
    )


def previous_document(key="notice-documents/example.txt", text="Original source",
                      status="FAILED"):
    return SimpleNamespace(
        id=uuid4(),
        notice_version_id=uuid4(),
        document_order=0,
        source_field="stdNtceDocUrl",
        storage_key=key,
        name="example.txt",
        content_type="text/plain",
        file_sha256=hashlib.sha256(b"New source").hexdigest(),
        file_size_bytes=len(b"New source"),
        download_status="DOWNLOADED",
        extraction_status=status,
        extraction_error="former retry failed",
        extracted_text=text,
        extracted_blocks=[{"block_index": 0, "location": "text", "text": text}],
        extracted_char_count=len(text),
        extracted_text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        text_extractor="PLAIN_TEXT_UTF-8-SIG",
        extracted_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 8, tzinfo=timezone.utc),
    )


class S3Error(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}
        super().__init__(code)


@pytest.mark.parametrize(
    ("error", "category", "attempts"),
    [
        (S3Error("AccessDenied"), "SOURCE_ACCESS_DENIED", 1),
        (S3Error("NoSuchKey"), "SOURCE_MISSING", 1),
        (S3Error("503"), "SOURCE_READ_FAILED", 2),
        (S3Error("504"), "SOURCE_READ_FAILED", 2),
        (TimeoutError("slow stream"), "SOURCE_READ_FAILED", 2),
    ],
)
@pytest.mark.parametrize("previous_status", ["FAILED", "PENDING"])
def test_preserves_verified_original_when_s3_read_fails(
    tmp_path, monkeypatch, error, category, attempts, previous_status
):
    record = previous_document(status=previous_status)
    before = (
        record.extracted_text, record.extracted_blocks, record.extracted_text_sha256,
        record.extracted_at, record.text_extractor, record.extracted_char_count,
    )
    client = Mock()
    client.get_object.side_effect = error
    monkeypatch.setattr(processing, "build_s3_client", lambda **kw: client)
    processing.process_document(record, settings=settings(tmp_path, "S3"))
    assert record.extraction_status == "FAILED"
    assert record.extraction_error == category
    assert (
        record.extracted_text, record.extracted_blocks, record.extracted_text_sha256,
        record.extracted_at, record.text_extractor, record.extracted_char_count,
    ) == before
    assert client.get_object.call_count == attempts
    client.put_object.assert_not_called()


@pytest.mark.parametrize(
    ("effect", "expected"),
    [("raised", "PARSER_FAILED"), ("returned", "PARSER_FAILED:")],
)
def test_parser_failure_preserves_history_and_never_publishes_it(
    tmp_path, monkeypatch, effect, expected
):
    document = previous_document(key="example.txt")
    (tmp_path / "example.txt").write_bytes(b"New source")
    old = document.extracted_text_sha256
    def parser(candidate, source):
        if effect == "raised":
            raise RuntimeError("parser panic")
        candidate.extraction_status = "FAILED"
        candidate.extraction_error = "PdfReadError"
        candidate.extracted_text = "partial invalid new extract"
    monkeypatch.setattr(processing, "extract_into_document", parser)
    processing.process_document(document, settings=settings(tmp_path))
    assert document.extraction_status == "FAILED"
    assert document.extraction_error.startswith(expected)
    assert document.extracted_text == "Original source"
    assert document.extracted_text_sha256 == old


@pytest.mark.parametrize("status", ["EMPTY", "UNSUPPORTED"])
def test_non_successful_parser_outcome_is_inactive_and_retained(
    tmp_path, monkeypatch, status
):
    document = previous_document(key="example.txt")
    (tmp_path / "example.txt").write_bytes(b"New source")
    def parser(candidate, source):
        candidate.extraction_status = status
        candidate.extraction_error = "unsupported" if status == "UNSUPPORTED" else None
    monkeypatch.setattr(processing, "extract_into_document", parser)
    processing.process_document(document, settings=settings(tmp_path))
    assert document.extraction_status == status
    assert document.extracted_text == "Original source"


def test_failed_duplicate_never_copies_another_documents_prior_history(
    tmp_path, monkeypatch
):
    one = previous_document(text="Version A")
    two = previous_document(text="Version B")
    client = Mock()
    client.get_object.side_effect = S3Error("NoSuchKey")
    monkeypatch.setattr(processing, "build_s3_client", lambda **kw: client)
    class FakeDb:
        def scalars(self, statement):
            return SimpleNamespace(all=lambda: [one, two])
        def commit(self):
            pass
    results = processing.extract_pending_documents(
        FakeDb(), settings=settings(tmp_path, "S3"), limit=2, retry_failed=True
    )
    assert results["failed_count"] == 2
    assert one.extracted_text == "Version A"
    assert two.extracted_text == "Version B"
    assert one.extraction_status == two.extraction_status == "FAILED"
    client.get_object.assert_called_once()


def test_successful_retry_only_then_replaces_prior_extraction(tmp_path):
    document = previous_document(key="example.txt")
    (tmp_path / "example.txt").write_bytes(b"New source")
    processing.process_document(document, settings=settings(tmp_path))
    assert document.extraction_status == "EXTRACTED"
    assert document.extracted_text == "New source"
    assert document.extracted_text_sha256 == hashlib.sha256(b"New source").hexdigest()
    assert document.extraction_error is None


def test_extracted_row_is_not_reprocessed_without_state_transition(tmp_path, monkeypatch):
    doc = previous_document(status="EXTRACTED")
    factory = Mock()
    monkeypatch.setattr(processing, "build_s3_client", factory)
    processing.process_document(doc, settings=settings(tmp_path, "S3"))
    assert doc.extraction_status == "EXTRACTED"
    assert doc.extracted_text == "Original source"
    factory.assert_not_called()


def test_invalid_historical_payload_is_discarded_on_failure(tmp_path):
    doc = previous_document(key="missing.txt")
    doc.extracted_text_sha256 = "0" * 64
    processing.process_document(doc, settings=settings(tmp_path))
    assert doc.extraction_status == "FAILED"
    assert doc.extracted_text is None
    assert doc.extracted_text_sha256 is None
    assert doc.extracted_blocks is None


def test_failed_status_hides_preserved_history_from_text_api_and_inspector(tmp_path):
    doc = previous_document()
    class FakeDB:
        def scalar(self, query):
            return doc
    result = get_notice_document_text(
        notice_id=uuid4(), version_number=1, document_id=doc.id, db=FakeDB()
    )
    assert result.extraction_status == "FAILED"
    assert result.text is None
    assert result.blocks is None
    assert result.text_sha256 is None
    assert result.extractor is None
    assert find_snippets(version_number=1, document=doc) == []


def fingerprint_v7(version):
    """Reference PR #7's JSON-canonicalized extracted document input contract."""
    documents = build_qualification_analysis_input(version).documents
    payload = json.dumps(
        sorted(
            ({"document_id": item.document_id,
              "extracted_text_sha256": item.extracted_text_sha256}
             for item in documents),
            key=lambda item: item["document_id"],
        ), ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(("qualification-analysis-input-v1\n" + payload).encode()).hexdigest()


def test_preserved_failed_bytes_cannot_make_pr7_fingerprint_or_rag_current(
    tmp_path, monkeypatch
):
    doc = previous_document(key="example.txt", status="EXTRACTED")
    version = SimpleNamespace(
        notice_id=uuid4(), id=uuid4(), version_number=1, documents=[doc]
    )
    fresh_hash = fingerprint_v7(version)
    assert len(build_notice_version_records(version)) == 1
    # Simulate a previously observed stale/retry row retaining its last good text.
    doc.extraction_status = "FAILED"
    (tmp_path / "example.txt").write_bytes(b"New source")
    def parser(candidate, source):
        raise ValueError("new parsing failed")
    monkeypatch.setattr(processing, "extract_into_document", parser)
    processing.process_document(doc, settings=settings(tmp_path))
    assert doc.extracted_text == "Original source"
    assert doc.extraction_status == "FAILED"
    assert fingerprint_v7(version) != fresh_hash
    assert build_qualification_analysis_input(version).documents == []
    assert build_notice_version_records(version) == []
    # In a future PR #7 merge, assert against the actual implementation too.
    from apps.api.app.qualification import analysis
    if hasattr(analysis, "qualification_analysis_version_fingerprint"):
        assert analysis.qualification_analysis_version_fingerprint(version) == fingerprint_v7(version)



def test_original_sha_mismatch_preserves_valid_history_but_is_not_current(tmp_path):
    doc = previous_document(key="example.txt")
    (tmp_path / "example.txt").write_bytes(b"different replacement")
    previous_text_sha = doc.extracted_text_sha256
    processing.process_document(doc, settings=settings(tmp_path))
    assert doc.extraction_status == "FAILED"
    assert doc.extraction_error == "SOURCE_SIZE_MISMATCH"
    assert doc.extracted_text == "Original source"
    assert doc.extracted_text_sha256 == previous_text_sha
    assert build_notice_version_records(
        SimpleNamespace(id=uuid4(), notice_id=uuid4(), version_number=1, documents=[doc])
    ) == []


def test_inconsistent_history_must_be_cleared_after_403(tmp_path, monkeypatch):
    record = previous_document()
    record.extracted_blocks[0]["text"] = "not matching historical text"
    client = Mock()
    client.get_object.side_effect = S3Error("AccessDenied")
    monkeypatch.setattr(processing, "build_s3_client", lambda **kw: client)
    processing.process_document(record, settings=settings(tmp_path, "S3"))
    assert record.extraction_status == "FAILED"
    assert record.extraction_error == "SOURCE_ACCESS_DENIED"
    assert record.extracted_blocks is None
    assert record.extracted_text_sha256 is None
