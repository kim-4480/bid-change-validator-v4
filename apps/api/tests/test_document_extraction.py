from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from apps.api.app.services.document_extraction import (
    UnsupportedDocumentError,
    _decode_hwp_paragraph_text,
    extract_document,
    extract_into_document,
)


def _hwp_control(code: int, control_id: bytes = b"\0\0\0\0") -> bytes:
    assert len(control_id) == 4
    return (
        code.to_bytes(2, "little")
        + control_id
        + b"\0" * 8
        + code.to_bytes(2, "little")
    )


def test_hwp_paragraph_text_skips_inline_and_extended_controls() -> None:
    payload = b"".join(
        (
            _hwp_control(2, b"dces"),
            "전북대학교 ".encode("utf-16le"),
            _hwp_control(11, b" osg"),
            "남원글로컬캠퍼스".encode("utf-16le"),
            (13).to_bytes(2, "little"),
        )
    )

    assert _decode_hwp_paragraph_text(payload) == "전북대학교 남원글로컬캠퍼스"


def test_hwp_paragraph_text_preserves_visible_character_controls() -> None:
    payload = b"".join(
        (
            "첫째".encode("utf-16le"),
            (10).to_bytes(2, "little"),
            "둘째".encode("utf-16le"),
            _hwp_control(9),
            "항목".encode("utf-16le"),
            (30).to_bytes(2, "little"),
            "끝".encode("utf-16le"),
        )
    )

    assert _decode_hwp_paragraph_text(payload) == "첫째\n둘째\t항목 끝"


def test_hwp_paragraph_text_rejects_truncated_structured_control() -> None:
    with pytest.raises(ValueError, match="invalid HWP paragraph control record"):
        _decode_hwp_paragraph_text((11).to_bytes(2, "little") + b" osg")


def test_hwp_extension_with_hwpml_xml_is_extracted() -> None:
    source = BytesIO(
        """<?xml version="1.0" encoding="UTF-8"?>
        <HWPML Version="2.8">
          <BODY>
            <SECTION Id="0">
              <P><TEXT><CHAR>입찰 참가자격<TAB/>중소기업</CHAR></TEXT></P>
              <P><TEXT><CHAR>실적 4억원<LINEBREAK/>이상</CHAR></TEXT></P>
            </SECTION>
          </BODY>
        </HWPML>
        """.encode("utf-8")
    )

    result = extract_document(
        source,
        filename="공고문.hwp",
        content_type="application/x-hwp",
    )

    assert result.extractor == "HWPML_XML"
    assert result.text == "입찰 참가자격 중소기업\n\n실적 4억원\n이상"
    assert result.blocks[1]["location"] == "section 1 · paragraph 2"


def test_non_hwpml_xml_with_hwp_extension_is_rejected() -> None:
    with pytest.raises(UnsupportedDocumentError, match="not HWPML"):
        extract_document(
            BytesIO(b"<?xml version='1.0'?><root><P>not hwpml</P></root>"),
            filename="fake.hwp",
            content_type="application/x-hwp",
        )


def test_hwp_extension_with_hwpx_zip_is_extracted() -> None:
    # G2B can provide an HWPX (ZIP) payload with a legacy .hwp filename.
    from zipfile import ZipFile

    source = BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr(
            "Contents/section0.xml",
            "<section><p><t>HWPX content from .hwp</t></p></section>",
        )

    result = extract_document(
        source,
        filename="misnamed.hwp",
        content_type="application/octet-stream",
    )

    assert result.extractor == "HWPX_XML"
    assert result.text == "HWPX content from .hwp"
    assert len(result.blocks) == 1


@pytest.mark.parametrize("filename", ["encrypted.hwpx", "misnamed.hwp"])
def test_encrypted_hwpx_section_is_unsupported(filename: str) -> None:
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", b"\x73\x02\x41\xbf encrypted payload")
        archive.writestr(
            "META-INF/manifest.xml",
            '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
            '<manifest:file-entry manifest:full-path="Contents/section0.xml">'
            '<manifest:encryption-data/>'
            '</manifest:file-entry></manifest:manifest>',
        )

    document = SimpleNamespace(name=filename, content_type="application/octet-stream")
    extract_into_document(document, source)

    assert document.extraction_status == "UNSUPPORTED"
    assert document.extracted_text is None
    assert document.extracted_text_sha256 is None
    assert "encrypted HWPX" in document.extraction_error


def test_malformed_unencrypted_hwpx_remains_failed() -> None:
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("Contents/section0.xml", b"not XML")

    document = SimpleNamespace(name="broken.hwpx", content_type="application/octet-stream")
    extract_into_document(document, source)

    assert document.extraction_status == "FAILED"


def test_encrypted_unrelated_hwpx_entry_does_not_hide_plain_section() -> None:
    source = BytesIO()
    with ZipFile(source, "w") as archive:
        archive.writestr("Contents/section0.xml", "<section><p><t>Readable</t></p></section>")
        archive.writestr(
            "META-INF/manifest.xml",
            '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0">'
            '<manifest:file-entry manifest:full-path="Preview/PrvText.txt">'
            '<manifest:encryption-data/>'
            '</manifest:file-entry></manifest:manifest>',
        )

    result = extract_document(source, filename="plain.hwpx", content_type=None)

    assert result.extractor == "HWPX_XML"
    assert result.text == "Readable"
