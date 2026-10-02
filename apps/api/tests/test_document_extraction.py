from io import BytesIO

import pytest

from apps.api.app.services.document_extraction import (
    UnsupportedDocumentError,
    _decode_hwp_paragraph_text,
    extract_document,
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
