"""PDF crypto provider integration with the pinned pypdf fork."""

from io import BytesIO

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.errors import FileNotDecryptedError
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from apps.api.app.services.document_extraction import (
    UnsupportedDocumentError,
    extract_document,
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


def test_unknown_format_is_still_unsupported() -> None:
    with pytest.raises(UnsupportedDocumentError):
        extract_document(BytesIO(b"not a PDF"), filename="unknown.bin", content_type=None)
