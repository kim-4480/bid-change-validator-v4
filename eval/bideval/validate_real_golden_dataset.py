"""Read-only storage validation; deliberately independent of quality_eval and DB."""

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileRef(StrictModel):
    path: str
    sha256: Digest


class Manifest(StrictModel):
    schema_version: Literal["qualification-real-storage-v1"]
    dataset_id: Literal["qualification-real-v0.1"]
    snapshot_archive_sha256: Digest
    snapshot_location: str
    semantic_labels: list[dict] = Field(max_length=0)
    cases: list[FileRef] = Field(min_length=5, max_length=5)


class Version(StrictModel):
    version_key: str
    notice_version_id: UUID | None
    version_number: Annotated[int, Field(strict=True, ge=1)] | None
    bid_notice_order: str
    metadata: dict


class Document(StrictModel):
    document_key: str
    document_id: UUID | None
    version_key: str
    notice_version_id: UUID | None
    name: str
    source_file_sha256: Digest
    source_snapshot_path: str
    extracted_text_sha256: Digest
    blocks_file_sha256: Digest
    text: FileRef
    blocks: FileRef
    metadata: dict


class Provenance(StrictModel):
    kind: Literal["real"]
    snapshot_path: str
    snapshot_sha256: Digest
    identity_note: str


class Case(StrictModel):
    case_id: Literal["G2", "C04", "C01", "C02", "C03"]
    notice_no: str
    golden_class: Literal["PRODUCT_GOLDEN", "SOURCE_GOLDEN"]
    identity_status: Literal["VERIFIED", "PARTIAL", "UNAVAILABLE"]
    notice_id: UUID | None
    notice_metadata: dict
    provenance: Provenance
    versions: list[Version] = Field(min_length=1)
    documents: list[Document] = Field(min_length=1)
    observations: list[FileRef]


class Location(StrictModel):
    page: Literal[6]
    block_index: Literal[5]
    section: Literal["2. 입찰 참가자격"]
    item: Literal["2)"]


class ObservationSource(StrictModel):
    snapshot_observation: str
    sha256: Digest


class Observation(StrictModel):
    observation_id: Literal["G2-region-clause-removal-candidate"]
    observed_change: Literal["candidate_removed"]
    review_status: Literal["DRAFT"]
    baseline_version_id: Literal["f44f265d-f1a3-4463-99ac-399aef98d69b"]
    current_version_id: Literal["c9d11d84-816b-4a95-ae9c-90e73f5de7e7"]
    baseline_document_id: Literal["c17fc7f6-eca6-4ca0-afef-86efe376a431"]
    current_document_id: Literal["f0790ad7-01ed-48ac-bd45-ccf246d8ee84"]
    quote: str = Field(min_length=1)
    location: Location
    current_checked_document_ids: list[UUID] = Field(min_length=4, max_length=4)
    absence_check: str
    qualification_before: str
    qualification_after: str
    diff: list[str]
    provenance: ObservationSource
    not_ground_truth: Literal[True]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def safe_path(root: Path, name: str) -> Path:
    # Reject Windows paths even when validating on Linux, and resolve symlinks.
    require(bool(name) and "\\" not in name and ":" not in name, f"Unsafe path: {name}")
    path = (root / name).resolve()
    require(not Path(name).is_absolute() and path.is_relative_to(root.resolve()), f"Path escape: {name}")
    return path


def hashed_file(root: Path, name: str, expected: str) -> Path:
    path = safe_path(root, name)
    require(path.is_file(), f"Missing file: {name}")
    require(hashlib.sha256(path.read_bytes()).hexdigest() == expected, f"Hash mismatch: {name}")
    return path


def checksum_inventory(root: Path, filename: str) -> set[str]:
    paths = set()
    for line in (root / filename).read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "Invalid checksum")
        require(name not in paths, f"Duplicate checksum path: {name}")
        hashed_file(root, name, digest)
        paths.add(name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    require(paths == actual - {filename}, "Checksum inventory does not cover exactly all files")
    return paths


def read_ref(root: Path, ref: FileRef, model):
    return model.model_validate_json(hashed_file(root, ref.path, ref.sha256).read_bytes())


def validate_dataset(root: Path, snapshot: Path | None = None) -> dict:
    root = root.resolve()
    inventory = checksum_inventory(root, "checksums.sha256")
    referenced = {".gitattributes", "README.md", "labels/README.md", "manifest.json"}
    manifest = Manifest.model_validate_json((root / "manifest.json").read_bytes())
    if snapshot is not None:
        checksum_inventory(snapshot, "SHA256SUMS.txt")
        archive = snapshot.with_suffix(".zip")
        hashed_file(archive.parent, archive.name, manifest.snapshot_archive_sha256)
    cases = [read_ref(root, ref, Case) for ref in manifest.cases]
    referenced.update(ref.path for ref in manifest.cases)
    require(len({c.case_id for c in cases}) == len(cases), "Duplicate case ID")
    expected = {"G2": "R26BK01686455", "C04": "R26BK01687395", "C01": "R26BK01705963",
                "C02": "R26BK01715895", "C03": "R26BK01716363"}
    document_keys, document_ids, version_ids = set(), set(), set()
    originals = 0
    for case in cases:
        require(case.notice_no == expected[case.case_id], "Notice number mismatch")
        product = case.case_id in {"G2", "C04"}
        require(case.golden_class == ("PRODUCT_GOLDEN" if product else "SOURCE_GOLDEN"), "Golden class mismatch")
        require((case.notice_id is not None) == product, "Invalid notice identity")
        require((case.identity_status == "VERIFIED") == product, "Invalid identity status")
        require(case.notice_metadata.get("id") == (str(case.notice_id) if product else None), "Notice metadata identity mismatch")
        versions = {v.version_key: v for v in case.versions}
        require(len(versions) == len(case.versions), "Duplicate version key")
        for version in case.versions:
            require((version.notice_version_id is not None) == product, "Invalid version identity")
            require((version.version_number is not None) == product, "Invalid version number")
            require(version.metadata.get("id") == (str(version.notice_version_id) if product else None), "Version metadata identity mismatch")
            require(version.metadata.get("version_number") == version.version_number, "Version metadata number mismatch")
            if version.notice_version_id is not None:
                require(version.notice_version_id not in version_ids, "Duplicate version ID")
                version_ids.add(version.notice_version_id)
        safe_path(root, case.provenance.snapshot_path)
        source_documents = None
        if snapshot is not None:
            source_path = hashed_file(snapshot, case.provenance.snapshot_path, case.provenance.snapshot_sha256)
            source = json.loads(source_path.read_bytes())
            source_documents = ([d for v in source["versions"] for d in v["documents"]]
                                if product else source["documents"])
            require(len(source_documents) == len(case.documents), "Snapshot document count mismatch")
        for doc in case.documents:
            referenced.update((doc.text.path, doc.blocks.path))
            require(doc.document_key not in document_keys, "Duplicate document key")
            document_keys.add(doc.document_key)
            require((doc.document_id is not None) == product, "Invalid document identity")
            require(doc.metadata.get("id" if product else "document_id") == (str(doc.document_id) if product else None), "Document metadata identity mismatch")
            if doc.document_id is not None:
                require(doc.document_id not in document_ids, "Duplicate document ID")
                document_ids.add(doc.document_id)
            require(doc.version_key in versions, "Missing document version")
            require(doc.notice_version_id == versions[doc.version_key].notice_version_id, "Document version mismatch")
            require(doc.text.sha256 == doc.extracted_text_sha256, "Original text hash mismatch")
            require(doc.blocks.sha256 == doc.blocks_file_sha256, "Blocks hash mismatch")
            text = hashed_file(root, doc.text.path, doc.extracted_text_sha256).read_text(encoding="utf-8")
            blocks = json.loads(hashed_file(root, doc.blocks.path, doc.blocks_file_sha256).read_bytes())
            require(isinstance(blocks, list), "Blocks must be an array")
            require(doc.metadata["file_sha256"] == doc.source_file_sha256, "Source hash not preserved")
            require(doc.metadata["extracted_text_sha256"] == doc.extracted_text_sha256, "Text hash not preserved")
            safe_path(root, doc.source_snapshot_path)
            if source_documents is not None:
                original = next((d for d in source_documents
                                 if (d.get("id") == str(doc.document_id) if product
                                     else d.get("cache_key") == doc.metadata["cache_key"])), None)
                require(original is not None, "Document absent from snapshot")
                require(original["extracted_text"] == text, "Snapshot text changed")
                require(original["extracted_blocks"] == blocks, "Snapshot blocks changed")
                require(original["extracted_text_sha256"] == doc.extracted_text_sha256, "Snapshot text hash changed")
                require({k: v for k, v in original.items() if k not in {"extracted_text", "extracted_blocks"}} == doc.metadata, "Snapshot document metadata changed")
                hashed_file(snapshot, doc.source_snapshot_path, doc.source_file_sha256)
                originals += 1
        require(len(case.observations) == (1 if case.case_id == "G2" else 0), "Unexpected observations")
        if case.observations:
            referenced.update(ref.path for ref in case.observations)
            observation = read_ref(root, case.observations[0], Observation)
            documents = {str(d.document_id): d for d in case.documents}
            baseline = documents[observation.baseline_document_id]
            current = documents[observation.current_document_id]
            require(str(baseline.notice_version_id) == observation.baseline_version_id, "G2 baseline linkage")
            require(str(current.notice_version_id) == observation.current_version_id, "G2 current linkage")
            require(versions[baseline.version_key].version_number == 1 and versions[baseline.version_key].bid_notice_order == "000", "G2 baseline order")
            require(versions[current.version_key].version_number == 2 and versions[current.version_key].bid_notice_order == "001", "G2 current order")
            blocks = json.loads(safe_path(root, baseline.blocks.path).read_bytes())
            block = blocks[observation.location.block_index]
            require(block["page"] == 6 and observation.quote in block["text"], "G2 source location mismatch")
            checked = {d.document_id for d in case.documents if str(d.notice_version_id) == observation.current_version_id}
            require(checked == set(observation.current_checked_document_ids), "G2 current attachment coverage")
            normalized_quote = "".join(observation.quote[3:].split())
            for doc in case.documents:
                if doc.document_id in checked:
                    require(normalized_quote not in "".join(safe_path(root, doc.text.path).read_text(encoding="utf-8").split()), "G2 sentence present in current")
            safe_path(root, observation.provenance.snapshot_observation)
            if snapshot is not None:
                hashed_file(snapshot, observation.provenance.snapshot_observation, observation.provenance.sha256)
    require(referenced == inventory, "Unreferenced file or missing Dataset reference")
    return {"cases": len(cases), "documents": len(document_keys), "product_cases": 2,
            "source_cases": 3, "ground_truth_labels": 0, "observations": 1,
            "text_files": len(list(root.rglob("*.txt"))),
            "blocks_files": len(list(root.rglob("*.blocks.json"))),
            "external_originals_verified": originals}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, help="Optional original export directory; requires its sibling ZIP")
    args = parser.parse_args()
    print(json.dumps(validate_dataset(args.dataset, args.snapshot), indent=2))
