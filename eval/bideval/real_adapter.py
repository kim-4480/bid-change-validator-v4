"""Read-only real Dataset adapter; run with --dataset PATH [--cases C01 G2].

Product versions expose a QualificationAnalysisInput; Source versions expose
only nullable identity and selection data. No extractor or DB is invoked.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from bideval.validate_real_golden_dataset import Case, Manifest, Version, hashed_file, read_ref, validate_dataset
from bidengine.pipeline.analysis_pipeline import QualificationAnalysisInput
from bidengine.document.backend_blocks import canonical_source_blocks
from bideval.runner import chunk_and_select
from bideval.scoring import score_case


@dataclass(frozen=True)
class RealCase:
    spec: Case
    version: Version
    documents: list[dict]
    analysis_input: QualificationAnalysisInput | None


def load_real_cases(root: Path, case_ids=("C01", "G2")) -> list[RealCase]:
    validate_dataset(root)
    manifest = Manifest.model_validate_json((root / "manifest.json").read_bytes())
    specs = [read_ref(root, ref, Case) for ref in manifest.cases]
    if not case_ids or set(case_ids) - {s.case_id for s in specs}:
        raise ValueError("Unknown or empty case selection")
    cases = []
    for spec in specs:
        if spec.case_id not in case_ids:
            continue
        for version in spec.versions:
            documents = []
            for doc in spec.documents:
                if doc.version_key != version.version_key:
                    continue
                documents.append({
                    "document_key": doc.document_key,
                    "document_id": str(doc.document_id) if doc.document_id else None,
                    "notice_version_id": str(doc.notice_version_id) if doc.notice_version_id else None,
                    "source_file_sha256": doc.source_file_sha256,
                    "extracted_text_sha256": doc.extracted_text_sha256,
                    "blocks_file_sha256": doc.blocks_file_sha256,
                    "extracted_text": hashed_file(root, doc.text.path, doc.text.sha256).read_bytes().decode("utf-8"),
                    "extracted_blocks": json.loads(hashed_file(root, doc.blocks.path, doc.blocks.sha256).read_bytes()),
                })
            analysis_input = None
            if spec.golden_class == "PRODUCT_GOLDEN":
                analysis_input = QualificationAnalysisInput(
                    notice_id=str(spec.notice_id), notice_version_id=str(version.notice_version_id),
                    documents=[dict(document_id=d["document_id"], file_sha256=d["source_file_sha256"],
                                    extracted_text_sha256=d["extracted_text_sha256"],
                                    extracted_blocks=d["extracted_blocks"]) for d in documents])
            cases.append(RealCase(spec, version, documents, analysis_input))
    return cases


def evaluate_real_case(case: RealCase) -> dict:
    document_blocks = []
    identities = {}
    for doc in case.documents:
        # Core selection uses source identifiers to keep adjacent documents apart.
        # Source-only keys are transient, namespaced tokens, NEVER Backend IDs or
        # QualificationAnalysisInput. Restore explicit nullable IDs at the boundary.
        token = doc["document_id"] or f"dataset:{doc['document_key']}"
        identities[token] = doc
        document_blocks.append(canonical_source_blocks(
            document_id=token, blocks=doc["extracted_blocks"],
            file_sha256=doc["source_file_sha256"], text_sha256=doc["extracted_text_sha256"]))
    chunks, selected = chunk_and_select(document_blocks)
    report = score_case([], chunks, selected)
    for chunk in chunks:
        for block in chunk["source_blocks"]:
            doc = identities[block["document_id"]]
            block.update(document_id=doc["document_id"], document_key=doc["document_key"],
                         notice_version_id=doc["notice_version_id"], blocks_file_sha256=doc["blocks_file_sha256"])
    return {
        "case_id": case.spec.case_id, "notice_no": case.spec.notice_no,
        "version_key": case.version.version_key, "version_number": case.version.version_number,
        "notice_id": str(case.spec.notice_id) if case.spec.notice_id else None,
        "notice_version_id": str(case.version.notice_version_id) if case.version.notice_version_id else None,
        "golden_class": case.spec.golden_class, "identity_status": case.spec.identity_status,
        "mode": "selection-only", "model_quality_claim": False,
        "ground_truth_labels": 0, "extractor_calls": 0,
        "analysis_input_available": case.analysis_input is not None,
        "context_identifier_kind": "DB document_id" if case.analysis_input else "Dataset document_key",
        "documents": [{k: v for k, v in d.items() if k not in {"extracted_text", "extracted_blocks"}}
                      for d in case.documents],
        "selected_chunks": selected, **report,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=["C01", "G2"])
    args = parser.parse_args()
    print(json.dumps([evaluate_real_case(c) for c in load_real_cases(args.dataset, args.cases)],
                     ensure_ascii=False, indent=2))
