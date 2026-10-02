import hashlib
import re
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

import olefile
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import NoticeDocument, ProposalDocument


KST = ZoneInfo("Asia/Seoul")


# HWP 5.0 paragraph text stores inline and extended controls in the same
# WCHAR array as visible text. Both control types occupy eight WCHARs; decoding
# the complete payload as UTF-16LE turns their ASCII control IDs (for example
# ``dces`` for a section definition) into unrelated CJK glyphs.
_HWP_INLINE_CONTROL_CODES = frozenset({4, 5, 6, 7, 8, 9, 19, 20})
_HWP_EXTENDED_CONTROL_CODES = frozenset(
    {1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23}
)
_HWP_STRUCTURED_CONTROL_CODES = _HWP_INLINE_CONTROL_CODES | _HWP_EXTENDED_CONTROL_CODES


class UnsupportedDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class ExtractionResult:
    extractor: str
    text: str
    blocks: list[dict[str, Any]]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    value = re.sub(r"[ \t]+", " ", value)
    return "\n".join(line.strip() for line in value.splitlines()).strip()


def _finish(extractor: str, blocks: list[dict[str, Any]]) -> ExtractionResult:
    normalized_blocks: list[dict[str, Any]] = []
    for block in blocks:
        text = _normalize_text(str(block.get("text") or ""))
        if not text:
            continue
        normalized_blocks.append(
            {
                "block_index": len(normalized_blocks),
                **{key: value for key, value in block.items() if key != "text"},
                "text": text,
            }
        )
    return ExtractionResult(
        extractor=extractor,
        text="\n\n".join(block["text"] for block in normalized_blocks),
        blocks=normalized_blocks,
    )


def _decode_hwp_paragraph_text(payload: bytes) -> str:
    """Decode visible text while skipping HWP paragraph control records."""

    even_length = len(payload) - (len(payload) % 2)
    units = struct.unpack(f"<{even_length // 2}H", payload[:even_length])
    parts: list[str] = []
    visible = bytearray()

    def flush_visible() -> None:
        if visible:
            parts.append(visible.decode("utf-16le", errors="ignore"))
            visible.clear()

    index = 0
    while index < len(units):
        code = units[index]
        if code in _HWP_STRUCTURED_CONTROL_CODES:
            flush_visible()
            control_end = index + 7
            if control_end >= len(units) or units[control_end] != code:
                raise ValueError("invalid HWP paragraph control record")
            if code == 9:  # tab
                parts.append("\t")
            index += 8
            continue
        if code <= 31:
            flush_visible()
            if code == 10:  # line break
                parts.append("\n")
            elif code == 24:  # hyphen
                parts.append("-")
            elif code in {30, 31}:  # non-breaking/fixed-width space
                parts.append(" ")
            index += 1
            continue
        visible.extend(struct.pack("<H", code))
        index += 1

    flush_visible()
    return "".join(parts)


def _extract_hwpx(source: BinaryIO) -> ExtractionResult:
    source.seek(0)
    with ZipFile(source) as archive:
        section_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"Contents/section\d+\.xml", name, re.IGNORECASE)
            ),
            key=_natural_key,
        )
        if not section_names:
            raise UnsupportedDocumentError("HWPX section XML was not found")
        blocks: list[dict[str, Any]] = []
        for section_index, section_name in enumerate(section_names):
            root = ElementTree.fromstring(archive.read(section_name))
            paragraph_index = 0
            for element in root.iter():
                if _local_name(element.tag) != "p":
                    continue
                text = "".join(
                    child.text or ""
                    for child in element.iter()
                    if _local_name(child.tag) == "t"
                )
                blocks.append(
                    {
                        "section_index": section_index,
                        "paragraph_index": paragraph_index,
                        "location": f"section {section_index + 1} · paragraph {paragraph_index + 1}",
                        "text": text,
                    }
                )
                paragraph_index += 1
    return _finish("HWPX_XML", blocks)


def _extract_docx(source: BinaryIO) -> ExtractionResult:
    source.seek(0)
    with ZipFile(source) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = [element for element in root.iter() if _local_name(element.tag) == "p"]
    blocks = []
    for paragraph_index, paragraph in enumerate(paragraphs):
        text = "".join(
            child.text or ""
            for child in paragraph.iter()
            if _local_name(child.tag) == "t"
        )
        blocks.append(
            {
                "paragraph_index": paragraph_index,
                "location": f"paragraph {paragraph_index + 1}",
                "text": text,
            }
        )
    return _finish("DOCX_XML", blocks)


def _extract_hwp(source: BinaryIO) -> ExtractionResult:
    source.seek(0)
    with olefile.OleFileIO(source) as document:
        if not document.exists("FileHeader") or not document.exists("BodyText"):
            raise UnsupportedDocumentError("not a supported HWP compound document")
        header = document.openstream("FileHeader").read()
        if len(header) < 40:
            raise ValueError("invalid HWP file header")
        flags = struct.unpack_from("<I", header, 36)[0]
        if flags & 2:
            raise UnsupportedDocumentError("encrypted HWP is not supported")
        compressed = bool(flags & 1)

        section_names = sorted(
            (
                "/".join(parts)
                for parts in document.listdir()
                if len(parts) == 2
                and parts[0] == "BodyText"
                and parts[1].startswith("Section")
            ),
            key=_natural_key,
        )
        blocks: list[dict[str, Any]] = []
        for section_index, section_name in enumerate(section_names):
            data = document.openstream(section_name).read()
            if compressed:
                data = zlib.decompress(data, -15)
            position = 0
            paragraph_index = 0
            while position + 4 <= len(data):
                record_header = struct.unpack_from("<I", data, position)[0]
                position += 4
                tag_id = record_header & 0x3FF
                record_size = (record_header >> 20) & 0xFFF
                if record_size == 0xFFF:
                    if position + 4 > len(data):
                        break
                    record_size = struct.unpack_from("<I", data, position)[0]
                    position += 4
                payload = data[position : position + record_size]
                position += record_size
                if tag_id == 67:
                    blocks.append(
                        {
                            "section_index": section_index,
                            "paragraph_index": paragraph_index,
                            "location": f"section {section_index + 1} · paragraph {paragraph_index + 1}",
                            "text": _decode_hwp_paragraph_text(payload),
                        }
                    )
                    paragraph_index += 1
    return _finish("HWP5_BODYTEXT", blocks)


def _hwpml_character_text(element: ElementTree.Element) -> str:
    parts = [element.text or ""]
    for child in element:
        child_name = _local_name(child.tag).upper()
        if child_name == "LINEBREAK":
            parts.append("\n")
        elif child_name == "TAB":
            parts.append("\t")
        elif child_name == "HYPEN":
            parts.append("-")
        elif child_name in {"NBSPACE", "FWSPACE"}:
            parts.append(" ")
        else:
            parts.append(_hwpml_character_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _extract_hwpml(source: BinaryIO) -> ExtractionResult:
    source.seek(0)
    root = ElementTree.parse(source).getroot()
    if _local_name(root.tag).upper() != "HWPML":
        raise UnsupportedDocumentError("XML document is not HWPML")

    sections = [
        element
        for element in root.iter()
        if _local_name(element.tag).upper() == "SECTION"
    ]
    if not sections:
        sections = [root]

    blocks: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections):
        paragraph_index = 0
        for paragraph in section.iter():
            if _local_name(paragraph.tag).upper() != "P":
                continue
            text = "".join(
                _hwpml_character_text(character)
                for character in paragraph.iter()
                if _local_name(character.tag).upper() == "CHAR"
            )
            blocks.append(
                {
                    "section_index": section_index,
                    "paragraph_index": paragraph_index,
                    "location": f"section {section_index + 1} · paragraph {paragraph_index + 1}",
                    "text": text,
                }
            )
            paragraph_index += 1
    return _finish("HWPML_XML", blocks)


def _extract_pdf(source: BinaryIO) -> ExtractionResult:
    source.seek(0)
    reader = PdfReader(source)
    blocks = [
        {
            "page": page_number,
            "location": f"p.{page_number}",
            "text": page.extract_text() or "",
        }
        for page_number, page in enumerate(reader.pages, start=1)
    ]
    return _finish("PYPDF", blocks)


def _extract_plain_text(source: BinaryIO) -> ExtractionResult:
    source.seek(0)
    data = source.read()
    for encoding in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return _finish(
                f"PLAIN_TEXT_{encoding.upper()}",
                [{"location": "text", "text": data.decode(encoding)}],
            )
        except UnicodeDecodeError:
            pass
    raise ValueError("text encoding is not supported")


def extract_document(
    source: BinaryIO,
    *,
    filename: str,
    content_type: str | None,
) -> ExtractionResult:
    source.seek(0)
    signature = source.read(8)
    source.seek(0)
    suffix = Path(filename).suffix.lower()
    if signature.startswith(b"%PDF") or suffix == ".pdf":
        return _extract_pdf(source)
    if signature.startswith(b"\xd0\xcf\x11\xe0"):
        return _extract_hwp(source)
    if suffix in {".hwp", ".hml"}:
        try:
            return _extract_hwpml(source)
        except ElementTree.ParseError:
            source.seek(0)
            return _extract_hwp(source)
    if signature.startswith(b"PK") or suffix in {".hwpx", ".docx"}:
        try:
            with ZipFile(source) as archive:
                names = set(archive.namelist())
            source.seek(0)
            if any(name.lower().startswith("contents/section") for name in names):
                return _extract_hwpx(source)
            if "word/document.xml" in names:
                return _extract_docx(source)
        except BadZipFile as error:
            raise ValueError("invalid ZIP-based document") from error
    if suffix in {".txt", ".csv", ".md"} or (content_type or "").startswith("text/"):
        return _extract_plain_text(source)
    raise UnsupportedDocumentError("document format is not supported")


def extract_into_document(
    document: NoticeDocument | ProposalDocument,
    source: BinaryIO,
) -> None:
    try:
        result = extract_document(
            source,
            filename=document.name,
            content_type=document.content_type,
        )
        document.extracted_text = result.text or None
        document.extracted_blocks = result.blocks
        document.extracted_char_count = len(result.text)
        document.extracted_text_sha256 = (
            hashlib.sha256(result.text.encode("utf-8")).hexdigest() if result.text else None
        )
        document.text_extractor = result.extractor
        document.extracted_at = datetime.now(KST)
        document.extraction_status = "EXTRACTED" if result.text else "EMPTY"
        document.extraction_error = None
    except UnsupportedDocumentError as error:
        document.extraction_status = "UNSUPPORTED"
        document.extraction_error = str(error)[:500]
        document.extracted_at = datetime.now(KST)
    except Exception as error:
        document.extraction_status = "FAILED"
        document.extraction_error = f"텍스트 추출 실패 ({type(error).__name__})"
        document.extracted_at = datetime.now(KST)


def copy_extraction(
    source: NoticeDocument | ProposalDocument,
    target: NoticeDocument | ProposalDocument,
) -> None:
    target.extraction_status = source.extraction_status
    target.extracted_text = source.extracted_text
    target.extracted_blocks = source.extracted_blocks
    target.extracted_char_count = source.extracted_char_count
    target.extracted_text_sha256 = source.extracted_text_sha256
    target.text_extractor = source.text_extractor
    target.extracted_at = source.extracted_at
    target.extraction_error = source.extraction_error


def extract_pending_documents(
    db: Session,
    *,
    settings: Settings,
    limit: int,
    retry_failed: bool = False,
) -> dict[str, int]:
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
    extracted_by_storage_key: dict[str, NoticeDocument] = {}
    counts = {"EXTRACTED": 0, "EMPTY": 0, "UNSUPPORTED": 0, "FAILED": 0}

    for document in documents:
        assert document.storage_key is not None
        cached = extracted_by_storage_key.get(document.storage_key)
        if cached is not None:
            copy_extraction(cached, document)
        else:
            backend = settings.document_storage_backend.strip().upper()
            if backend == "LOCAL":
                root = Path(settings.document_storage_path).resolve()
                target = (root / document.storage_key).resolve()
                if root not in target.parents or not target.is_file():
                    document.extraction_status = "FAILED"
                    document.extraction_error = "저장된 첨부파일이 없습니다."
                    document.extracted_at = datetime.now(KST)
                else:
                    with target.open("rb") as source:
                        extract_into_document(document, source)
            elif backend == "S3":
                if not settings.document_s3_bucket:
                    raise ValueError("DOCUMENT_S3_BUCKET is required when backend is S3")
                from .document_storage import build_s3_client

                s3 = build_s3_client(
                    region=settings.aws_region,
                    endpoint_url=settings.document_s3_endpoint_url,
                )
                with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temp:
                    s3.download_fileobj(settings.document_s3_bucket, document.storage_key, temp)
                    extract_into_document(document, temp)
            else:
                raise ValueError("DOCUMENT_STORAGE_BACKEND must be LOCAL or S3")
            extracted_by_storage_key[document.storage_key] = document
        counts[document.extraction_status] = counts.get(document.extraction_status, 0) + 1

    db.commit()
    return {
        "requested_count": len(documents),
        "extracted_count": counts["EXTRACTED"],
        "empty_count": counts["EMPTY"],
        "unsupported_count": counts["UNSUPPORTED"],
        "failed_count": counts["FAILED"],
    }
