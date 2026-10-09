"""PDF crypto provider integration with the pinned pypdf fork."""

from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.errors import FileNotDecryptedError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from apps.api.app.config import Settings
from apps.api.app.services.document_extraction import (
    UnsupportedDocumentError,
    extract_document,
    extract_into_document,
    extract_pending_documents,
)


def _sample_pdf(*, algorithm: str | None = None, password: str = "") -> BytesIO:
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 30 100 Td (PDF extraction test) Tj ET")
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    page[NameObject("/Contents")] = writer._add_object(content)
    if algorithm:
        writer.encrypt(user_password=password, algorithm=algorithm)
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output


@pytest.mark.parametrize("algorithm", ["AES-128", "AES-256"])
def test_aes_pdf_without_user_password_extracts_text(algorithm: str) -> None:
    result = extract_document(
        _sample_pdf(algorithm=algorithm),
        filename="encrypted.pdf",
        content_type="application/pdf",
    )
    assert result.extractor == "PYPDF"
    assert result.text == "PDF extraction test"
    assert result.blocks[0]["page"] == 1


def test_unencrypted_pdf_still_extracts_text() -> None:
    result = extract_document(
        _sample_pdf(), filename="plain.pdf", content_type="application/pdf"
    )
    assert result.text == "PDF extraction test"


def test_password_protected_pdf_fails_without_valid_password() -> None:
    source = _sample_pdf(algorithm="AES-256", password="known-password")
    assert not PdfReader(source).decrypt("incorrect-password")
    source.seek(0)
    with pytest.raises(FileNotDecryptedError):
        extract_document(source, filename="protected.pdf", content_type="application/pdf")
    source.seek(0)
    reader = PdfReader(source)
    assert reader.decrypt("known-password")
    assert reader.pages[0].extract_text() == "PDF extraction test"


def test_unknown_format_is_still_unsupported() -> None:
    with pytest.raises(UnsupportedDocumentError):
        extract_document(BytesIO(b"not a PDF"), filename="unknown.bin", content_type=None)


# The extraction service must never expose old text after a failed retry.


def _document(name: str = "sample.pdf", storage_key: str = "sample.pdf") -> SimpleNamespace:
    return SimpleNamespace(
        name=name, content_type="application/pdf", storage_key=storage_key,
        download_status="DOWNLOADED", extraction_status="EXTRACTED",
        extracted_text="old text", extracted_blocks=[{"page": 1, "text": "old text"}],
        extracted_char_count=8, extracted_text_sha256=sha256(b"old text").hexdigest(),
        text_extractor="PYPDF", extracted_at=None, extraction_error=None,
    )


def test_reprocessing_broken_pdf_clears_previous_extraction() -> None:
    document = _document()
    extract_into_document(document, BytesIO(b"%PDF-1.7\ncorrupted"))
    assert document.extraction_status == "FAILED"
    assert "PdfStreamError" in document.extraction_error
    assert document.extracted_text is None
    assert document.extracted_blocks is None
    assert document.extracted_char_count == 0
    assert document.extracted_text_sha256 is None
    assert document.text_extractor is None


def test_reprocessing_unsupported_document_clears_previous_extraction() -> None:
    document = _document(name="not-supported.bin")
    extract_into_document(document, BytesIO(b"not a document"))
    assert document.extraction_status == "UNSUPPORTED"
    assert document.extracted_text is None
    assert document.extracted_blocks is None
    assert document.extracted_text_sha256 is None


def test_failed_pdf_followed_by_valid_pdf_still_extracts() -> None:
    broken = _document(storage_key="broken.pdf")
    extract_into_document(broken, BytesIO(b"%PDF-1.7\ncorrupted"))
    valid = _document()
    extract_into_document(valid, _sample_pdf(algorithm="AES-128"))
    assert broken.extraction_status == "FAILED"
    assert valid.extraction_status == "EXTRACTED"
    assert valid.extracted_text == "PDF extraction test"
    assert valid.extracted_text_sha256 == sha256(b"PDF extraction test").hexdigest()


def test_encrypted_pdf_skips_blank_page_but_preserves_page_number() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    page = writer.add_blank_page(width=300, height=300)
    content = DecodedStreamObject()
    content.set_data(b"BT /F1 12 Tf 30 100 Td (Second page) Tj ET")
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.encrypt(user_password="", algorithm="AES-256")
    out = BytesIO()
    writer.write(out)
    result = extract_document(out, filename="partially_blank.pdf", content_type="application/pdf")
    assert result.text == "Second page"
    assert [b["page"] for b in result.blocks] == [2]


class _FakeSession:
    def __init__(self, docs: list[SimpleNamespace]) -> None:
        self.docs = docs
        self.commits = 0

    def scalars(self, _query):
        return self

    def all(self):
        return self.docs

    def commit(self):
        self.commits += 1


def test_local_batch_handles_failure_duplicate_and_retry(tmp_path) -> None:
    (tmp_path / "broken.pdf").write_bytes(b"%PDF-1.7\ncorrupted")
    (tmp_path / "good.pdf").write_bytes(_sample_pdf(algorithm="AES-128").getvalue())
    failed = _document(storage_key="broken.pdf")
    good = _document(storage_key="good.pdf")
    duplicate = _document(storage_key="good.pdf")
    missing = _document(storage_key="notfound.pdf")
    db = _FakeSession([failed, good, duplicate, missing])
    settings = Settings(document_storage_backend="LOCAL", document_storage_path=str(tmp_path))
    for retry_number in range(2):
        outcome = extract_pending_documents(db, settings=settings, limit=4, retry_failed=True)
        assert outcome == {"requested_count": 4, "extracted_count": 2, "empty_count": 0, "unsupported_count": 0, "failed_count": 2}
        assert failed.extraction_status == missing.extraction_status == "FAILED"
        assert failed.extracted_text is None and missing.extracted_text is None
        assert good.extraction_status == duplicate.extraction_status == "EXTRACTED"
        assert good.extracted_text == duplicate.extracted_text == "PDF extraction test"
        assert good.extracted_text_sha256 == duplicate.extracted_text_sha256
        assert len(good.extracted_blocks) == len(duplicate.extracted_blocks) == 1
    assert db.commits == 2


def test_s3_download_error_does_not_abort_remaining_batch(monkeypatch) -> None:
    class StubS3:
        def download_fileobj(self, bucket, key, target):
            if key == "first.pdf":
                raise OSError("remote storage failure")
            target.write(_sample_pdf(algorithm="AES-128").getvalue())

    monkeypatch.setattr("apps.api.app.services.document_storage.build_s3_client", lambda **kwargs: StubS3())
    docs = [_document(storage_key="first.pdf"), _document(storage_key="second.pdf")]
    db = _FakeSession(docs)
    settings = Settings(document_storage_backend="S3", document_s3_bucket="isolated-test")
    result = extract_pending_documents(db, settings=settings, limit=2, retry_failed=True)
    assert result["failed_count"] == 1
    assert result["extracted_count"] == 1
    assert docs[0].extracted_text is None
    assert docs[1].extracted_text == "PDF extraction test"
    assert db.commits == 1


@pytest.mark.parametrize("algorithm", ["RC4-40", "RC4-128"])
def test_legacy_rc4_pdf_remains_supported(algorithm: str) -> None:
    result = extract_document(_sample_pdf(algorithm=algorithm), filename="old.pdf", content_type="application/pdf")
    assert result.text == "PDF extraction test"
    assert result.blocks[0]["page"] == 1


def test_pdf_signature_recognized_without_pdf_extension() -> None:
    result = extract_document(_sample_pdf(algorithm="AES-128"), filename="download.bin", content_type="application/octet-stream")
    assert result.text == "PDF extraction test"


def test_corrupt_pdf_with_pdf_extension_is_failed() -> None:
    doc = _document(name="corrupt.pdf")
    extract_into_document(doc, BytesIO(b"non-pdf bytes"))
    assert doc.extraction_status == "FAILED"
    assert doc.extracted_text is None and doc.extracted_text_sha256 is None


def test_aes_pdf_with_only_empty_pages_is_empty() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.encrypt(user_password="", algorithm="AES-128")
    source = BytesIO()
    writer.write(source)
    doc = _document(name="empty.pdf")
    extract_into_document(doc, source)
    assert doc.extraction_status == "EMPTY"
    assert doc.extracted_text is None
    assert doc.extracted_blocks == []
    assert doc.extracted_char_count == 0
    assert doc.extracted_text_sha256 is None


def test_malformed_pdf_font_extraction_error_records_failure(monkeypatch) -> None:
    class BadPage:
        def extract_text(self):
            raise KeyError("/DescendantFonts")

    class BadReader:
        def __init__(self, source):
            self.pages = [BadPage()]

    monkeypatch.setattr("apps.api.app.services.document_extraction.PdfReader", BadReader)
    doc = _document(name="badfont.pdf")
    extract_into_document(doc, BytesIO(b"%PDF-1.7\n"))
    assert doc.extraction_status == "FAILED"
    assert "KeyError" in doc.extraction_error
    assert doc.extracted_text is None and doc.extracted_text_sha256 is None
