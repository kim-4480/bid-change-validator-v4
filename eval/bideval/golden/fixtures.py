"""Read version-pinned block fixtures without Demo, parsers, network, or DB."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bidengine.pipeline.analysis_pipeline import QualificationAnalysisInput
from bideval.golden.spans import GoldenSpan


class FileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DocumentRef(FileRef):
    document_id: str
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    notice_id: str
    notice_no: str
    notice_version_id: str
    version_number: int = Field(ge=1)
    provenance: Literal["synthetic", "real", "derived"]
    provenance_note: str = Field(min_length=1)
    documents: list[DocumentRef] = Field(min_length=1)
    labels: FileRef
    synthetic_slots: list[dict[str, Any]] = Field(default_factory=list)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["quality-eval-v1"]
    dataset_id: str
    purpose: str
    profiles: FileRef
    cases: list[CaseSpec] = Field(min_length=1)


@dataclass(frozen=True)
class LoadedCase:
    spec: CaseSpec
    analysis_input: QualificationAnalysisInput
    spans: list[GoldenSpan]


@dataclass(frozen=True)
class Dataset:
    manifest: Manifest
    manifest_sha256: str
    cases: list[LoadedCase]


def _read(root: Path, ref: FileRef):
    path = (root / ref.path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("fixture path escapes dataset root")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != ref.sha256:
        raise ValueError(f"fixture hash mismatch: {ref.path}")
    return json.loads(data)


def load_dataset(root: Path) -> Dataset:
    data = (root / "manifest.json").read_bytes()
    manifest = Manifest.model_validate_json(data)
    _read(root, manifest.profiles)  # Reserved synthetic profiles, not judgment truth.
    cases = []
    seen_cases: set[str] = set()
    for spec in manifest.cases:
        if not spec.case_id or spec.case_id in seen_cases:
            raise ValueError("empty or duplicate case_id")
        seen_cases.add(spec.case_id)
        documents = []
        document_text = {}
        for ref in spec.documents:
            payload = _read(root, ref)
            if (payload["document_id"] != ref.document_id
                    or payload["notice_version_id"] != spec.notice_version_id):
                raise ValueError("document/version reference mismatch")
            blocks = payload["extracted_blocks"]
            text = "\n".join(block["text"] for block in blocks)
            text_hash = hashlib.sha256(text.encode()).hexdigest()
            if payload["extracted_text_sha256"] != text_hash:
                raise ValueError("extracted text hash mismatch")
            document_text[ref.document_id] = text
            documents.append(dict(document_id=ref.document_id,
                                  file_sha256=ref.source_sha256,
                                  extracted_text_sha256=text_hash,
                                  extracted_blocks=blocks))
        analysis_input = QualificationAnalysisInput(
            notice_id=spec.notice_id, notice_version_id=spec.notice_version_id,
            documents=documents)
        labels = _read(root, spec.labels)
        if labels["notice_version_id"] != spec.notice_version_id:
            raise ValueError("label/version reference mismatch")
        spans = [GoldenSpan.model_validate(item) for item in labels["spans"]]
        if len({s.span_id for s in spans}) != len(spans):
            raise ValueError("duplicate span_id")
        for span in spans:
            if span.document_id not in document_text or not span.is_in(document_text[span.document_id]):
                raise ValueError("label quote missing from referenced document")
        cases.append(LoadedCase(spec, analysis_input, spans))
    return Dataset(manifest, hashlib.sha256(data).hexdigest(), cases)
