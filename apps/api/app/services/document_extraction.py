import hashlib
import re
import struct
import zlib
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
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


class _HTMLBlockParser(HTMLParser):
    """Turn a downloaded HTML notice into text blocks, retaining table rows."""

    _BLOCK_TAGS = frozenset({"div", "p", "li", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6"})
    _SKIP_TAGS = frozenset({"head", "style", "script", "noscript"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict[str, Any]] = []
        self._parts: list[str] = []
        self._skip_depth = 0
        self._in_row = False
        self._cell_count = 0

    def _flush(self) -> None:
        text = "".join(self._parts).strip()
        if text:
            self.blocks.append({"location": f"html block {len(self.blocks) + 1}", "text": text})
        self._parts.clear()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "tr":
            self._flush()
            self._in_row = True
            self._cell_count = 0
        elif tag in {"td", "th"} and self._in_row:
            if self._cell_count:
                self._parts.append(" | ")
            self._cell_count += 1
        elif tag == "br":
            self._parts.append("\n")
        elif tag in self._BLOCK_TAGS and not self._in_row:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "tr":
            self._flush()
            self._in_row = False
        elif tag in self._BLOCK_TAGS and not self._in_row:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._parts.append(data)

    def finish(self) -> list[dict[str, Any]]:
        self._flush()
        return self.blocks


def _decode_text_bytes(data: bytes, *, content_type: str | None = None) -> tuple[str, str]:
    charset = re.search(r"charset\s*=\s*['\"]?([\w-]+)", content_type or "", re.IGNORECASE)
    encodings = ([charset.group(1)] if charset else []) + ["utf-8-sig", "cp949", "euc-kr"]
    for encoding in dict.fromkeys(encodings):
        try:
            return data.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            pass
    raise ValueError("text encoding is not supported")


def _extract_html(source: BinaryIO, *, content_type: str | None) -> ExtractionResult:
    source.seek(0)
    text, _ = _decode_text_bytes(source.read(), content_type=content_type)
    parser = _HTMLBlockParser()
    parser.feed(text)
    parser.close()
    return _finish("HTML_TEXT", parser.finish())


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
        manifest_name = next(
            (name for name in archive.namelist() if name.casefold() == "meta-inf/manifest.xml"),
            None,
        )
        if manifest_name is not None:
            manifest = ElementTree.fromstring(archive.read(manifest_name))
            section_paths = {name.casefold() for name in section_names}
            for entry in manifest.iter():
                if _local_name(entry.tag) != "file-entry":
                    continue
                path = next(
                    (value for key, value in entry.attrib.items() if _local_name(key) == "full-path"),
                    "",
                )
                if path.lstrip("/").casefold() not in section_paths:
                    continue
                if any(_local_name(child.tag) == "encryption-data" for child in entry):
                    raise UnsupportedDocumentError("encrypted HWPX section is not supported")
        # Automatic numbering is defined in header.xml, not inline text nodes.
        numbering_rules = {}
        paragraph_rules = {}
        header_name = next((n for n in archive.namelist() if n.casefold() == "contents/header.xml"), None)
        if header_name:
            header_root = ElementTree.fromstring(archive.read(header_name))
            for node in header_root.iter():
                name = _local_name(node.tag)
                if name == "numbering":
                    rules = {}
                    for head in node:
                        if _local_name(head.tag) == "paraHead":
                            try:
                                level = int(head.get("level", "0"))
                                initial = int(head.get("start", "1"))
                            except ValueError:
                                continue
                            rules[level] = (head.text or "", head.get("numFormat", "DIGIT"), initial)
                    numbering_rules[node.get("id", "")] = rules
                elif name == "paraPr":
                    heading = next((child for child in node if _local_name(child.tag) == "heading"), None)
                    if heading is not None and heading.get("type", "").upper() == "NUMBER":
                        try:
                            paragraph_rules[node.get("id", "")] = (heading.get("idRef", ""), int(heading.get("level", "0")))
                        except ValueError:
                            pass
        counters = {}

        def numbering_label(paragraph: ElementTree.Element) -> str:
            rule = paragraph_rules.get(paragraph.get("paraPrIDRef", ""))
            if not rule:
                return ""
            numbering_id, raw_level = rule
            levels = numbering_rules.get(numbering_id, {})
            level = raw_level + 1 if raw_level + 1 in levels else raw_level
            if level not in levels:
                return ""
            template, fmt, initial = levels[level]
            if not re.search(r"\^[1-9]", template):
                return ""
            key = (numbering_id, level)
            counters[key] = counters.get(key, initial - 1) + 1
            for other in list(counters):
                if other[0] == numbering_id and other[1] > level:
                    del counters[other]
            def number_text(value: int, form: str) -> str | None:
                if form == "DIGIT":
                    return str(value)
                if form == "HANGUL_SYLLABLE":
                    chars = "가나다라마바사아자차카타파하"
                    return chars[value - 1] if 1 <= value <= len(chars) else None
                if form in ("LATIN_CAPITAL", "LATIN_SMALL"):
                    if not 1 <= value <= 26:
                        return None
                    return chr((65 if form == "LATIN_CAPITAL" else 97) + value - 1)
                if form == "CIRCLED_DIGIT" and 1 <= value <= 20:
                    return chr(0x2460 + value - 1)
                return None
            def substitute(match: re.Match[str]) -> str:
                depth = int(match.group(1))
                if depth not in levels:
                    raise ValueError("missing numbering level")
                previous = counters.get((numbering_id, depth), levels[depth][2])
                result = number_text(previous, levels[depth][1])
                if result is None:
                    raise ValueError("unsupported number format")
                return result
            try:
                return re.sub(r"\^([1-9])", substitute, template).strip()
            except ValueError:
                return ""

        blocks: list[dict[str, Any]] = []
        for section_index, section_name in enumerate(section_names):
            root = ElementTree.fromstring(archive.read(section_name))
            parents = {child: parent for parent in root.iter() for child in parent}

            def nearest_ancestor(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
                parent = parents.get(element)
                while parent is not None:
                    if _local_name(parent.tag) == name:
                        return parent
                    parent = parents.get(parent)
                return None

            def text_node_value(node: ElementTree.Element) -> str:
                parts = [node.text or ""]
                for child in node:
                    kind = _local_name(child.tag).lower()
                    if kind in {"linebreak", "br"}:
                        parts.append("\n")
                    elif kind == "tab":
                        parts.append("\t")
                    elif kind in {"hyphen", "hypen"}:
                        parts.append("-")
                    elif kind in {"nbspace", "fwspace"}:
                        parts.append(" ")
                    else:
                        parts.append(text_node_value(child))
                    parts.append(child.tail or "")
                return "".join(parts)

            def paragraph_text(paragraph: ElementTree.Element) -> str:
                content = "".join(
                    text_node_value(child)
                    for child in paragraph.iter()
                    if _local_name(child.tag) == "t"
                    and nearest_ancestor(child, "p") is paragraph
                )
                label = numbering_label(paragraph)
                return f"{label} {content}".strip() if label and not content.lstrip().startswith(label) else content

            row_indices = {
                row: index
                for index, row in enumerate(
                    (element for element in root.iter() if _local_name(element.tag) == "tr"),
                    start=1,
                )
            }
            emitted_rows: set[ElementTree.Element] = set()
            paragraph_index = 0
            for element in root.iter():
                if _local_name(element.tag) != "p":
                    continue
                row = nearest_ancestor(element, "tr")
                cell = nearest_ancestor(element, "tc")
                if row is not None and cell is not None:
                    if row in emitted_rows:
                        paragraph_index += 1
                        continue
                    emitted_rows.add(row)
                    cells = [
                        item for item in row.iter()
                        if _local_name(item.tag) == "tc"
                        and nearest_ancestor(item, "tr") is row
                    ]
                    cell_texts = []
                    cell_metadata = []
                    for cell_ordinal, table_cell in enumerate(cells):
                        paragraphs = [
                            paragraph_text(item)
                            for item in table_cell.iter()
                            if _local_name(item.tag) == "p"
                            and nearest_ancestor(item, "tc") is table_cell
                        ]
                        value = " / ".join(text for text in paragraphs if text.strip())
                        cell_texts.append(value)
                        addr = next((n for n in table_cell if _local_name(n.tag) == "cellAddr"), None)
                        span = next((n for n in table_cell if _local_name(n.tag) == "cellSpan"), None)
                        def cell_int(node: ElementTree.Element | None, attr: str, default: int) -> int:
                            try:
                                return int(node.get(attr, str(default))) if node is not None else default
                            except ValueError:
                                return default
                        cell_metadata.append({
                            "row": cell_int(addr, "rowAddr", row_indices[row] - 1),
                            "col": cell_int(addr, "colAddr", cell_ordinal),
                            "row_span": cell_int(span, "rowSpan", 1),
                            "col_span": cell_int(span, "colSpan", 1),
                            "text": value,
                        })
                    text = " | ".join(cell_texts)
                    location = f"section {section_index + 1} · table row {row_indices[row]}"
                else:
                    text = paragraph_text(element)
                    location = f"section {section_index + 1} · paragraph {paragraph_index + 1}"
                blocks.append(
                    {
                        "section_index": section_index,
                        "paragraph_index": paragraph_index,
                        "location": location,
                        "text": text,
                        **({"kind": "table_row", "cells": cell_metadata} if row is not None and cell is not None else {"kind": "paragraph"}),
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
    text, encoding = _decode_text_bytes(source.read())
    return _finish(
        f"PLAIN_TEXT_{encoding.upper()}",
        [{"location": "text", "text": text}],
    )


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
    # Some G2B downloads contain HWPML XML bytes under a .hwpx name.
    # Identify the actual XML payload before the ZIP-by-extension fallback.
    if suffix in {".hwp", ".hwpx", ".hml"} and signature.lstrip(
        b"\xef\xbb\xbf \t\r\n"
    ).lower().startswith((b"<?xml", b"<hwpml")):
        return _extract_hwpml(source)
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
    if suffix in {".hwp", ".hml"}:
        try:
            return _extract_hwpml(source)
        except ElementTree.ParseError:
            source.seek(0)
            return _extract_hwp(source)
    html_prefix = signature.lstrip().lower()
    if (
        suffix in {".html", ".htm"}
        or (content_type or "").lower().startswith("text/html")
        or html_prefix.startswith((b"<style", b"<html", b"<div", b"<!doctyp"))
    ):
        return _extract_html(source, content_type=content_type)
    if suffix in {".txt", ".csv", ".md"} or (content_type or "").startswith("text/"):
        return _extract_plain_text(source)
    raise UnsupportedDocumentError("document format is not supported")


def _clear_extraction_payload(document: NoticeDocument | ProposalDocument) -> None:
    """Remove stale text metadata before recording an unsuccessful retry."""
    document.extracted_text = None
    document.extracted_blocks = None
    document.extracted_char_count = 0
    document.extracted_text_sha256 = None
    document.text_extractor = None


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
        _clear_extraction_payload(document)
        document.extraction_status = "UNSUPPORTED"
        document.extraction_error = str(error)[:500]
        document.extracted_at = datetime.now(KST)
    except Exception as error:
        _clear_extraction_payload(document)
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
                    _clear_extraction_payload(document)
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
                try:
                    with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as temp:
                        s3.download_fileobj(settings.document_s3_bucket, document.storage_key, temp)
                        extract_into_document(document, temp)
                except Exception as error:
                    _clear_extraction_payload(document)
                    document.extraction_status = "FAILED"
                    document.extraction_error = f"첨부파일 다운로드 실패 ({type(error).__name__})"
                    document.extracted_at = datetime.now(KST)
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
