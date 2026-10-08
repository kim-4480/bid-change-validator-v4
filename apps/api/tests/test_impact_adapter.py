from types import SimpleNamespace
from bidengine.contracts import Evidence, EvidenceLocation, QualificationRequirement
from bidengine.pipeline.analysis_pipeline import QualificationDocumentInput
from apps.api.app.qualification.impact_adapter import (
    analysis_input_fingerprint, current_grounded_requirement_keys,
    snapshot_from_analysis,
)
from bidengine.diff.impact_plan import plan_requirement_impacts
from bidengine.contracts import Judgment

def fixture(version="v1", text="3. 서울 소재 업체"):
    document = QualificationDocumentInput(
        document_id="document-"+version, file_sha256="file-"+version,
        extracted_text_sha256="text-"+version,
        extracted_blocks=[{"block_index": 0, "page": 3, "text": text}],
    )
    req = QualificationRequirement(
        requirement_key="REQ", notice_version_id=version,
        type="REGION", operator="MATCH", value="서울",
        raw=text, evidence_keys=["E-1"], scope={"guard": "assessed"},
    )
    ev = Evidence(
        evidence_key="E-1", source_type="NOTICE_DOCUMENT",
        document_id=document.document_id, notice_version_id=version,
        location=EvidenceLocation(block_start=0, block_end=0, page=3),
        quote=text, source_sha256=document.file_sha256,
        extracted_text_sha256=document.extracted_text_sha256,
    )
    return document, req, ev

def test_source_quote_page_version_and_both_hashes_required():
    d, req, ev = fixture()
    assert current_grounded_requirement_keys([req],[ev],[d],notice_version_id="v1")=={"REQ"}
    altered = ev.model_copy(update={"extracted_text_sha256": "old"})
    assert not current_grounded_requirement_keys([req],[altered],[d],notice_version_id="v1")
    altered = ev.model_copy(update={"notice_version_id": "v0"})
    assert not current_grounded_requirement_keys([req],[altered],[d],notice_version_id="v1")
    altered = ev.model_copy(update={"location": EvidenceLocation(page=5)})
    assert not current_grounded_requirement_keys([req],[altered],[d],notice_version_id="v1")

def test_quote_no_longer_in_current_extracted_block():
    d, req, ev = fixture()
    replaced = d.model_copy(update={"extracted_blocks": [{"block_index": 0, "page": 3, "text": "3. 부산 소재 업체"}]})
    assert not current_grounded_requirement_keys([req],[ev],[replaced],notice_version_id="v1")

def test_024_without_input_fingerprint_is_not_current():
    d, _req, _ev = fixture()
    row = SimpleNamespace(id="run-v1", notice_version_id="v1", status="SUCCEEDED")
    snapshot=snapshot_from_analysis(row,notice_id="notice",documents=[d],
        company_snapshot={"region":"Seoul"},rule_version="r1",model_version="m1",
        all_documents_extracted=True)
    assert snapshot.input_fingerprint is None
    assert snapshot.verified_input_fingerprint
    assert snapshot.extraction_complete is True

def test_025_fingerprint_matches_exact_current_document_input():
    d, _req, _ev = fixture()
    computed=analysis_input_fingerprint([d])
    row=SimpleNamespace(id="run-v1",notice_version_id="v1",status="SUCCEEDED",input_fingerprint=computed)
    snapshot=snapshot_from_analysis(row,notice_id="notice",documents=[d],
        company_snapshot={"region":"Seoul"},rule_version="r1",model_version="m1",
        all_documents_extracted=True)
    assert snapshot.input_fingerprint == snapshot.verified_input_fingerprint
    assert snapshot.extraction_complete
    stale=snapshot_from_analysis(
        SimpleNamespace(id="run-v1",notice_version_id="v1",status="SUCCEEDED",input_fingerprint="old"),
        notice_id="notice",documents=[d],company_snapshot={"region":"Seoul"},
        rule_version="r1",model_version="m1",all_documents_extracted=True)
    assert stale.input_fingerprint != stale.verified_input_fingerprint

def test_missing_document_or_failed_run_never_complete():
    d, _, _ = fixture()
    row=SimpleNamespace(id="run",notice_version_id="v1",status="PARTIAL",input_fingerprint="fp")
    partial=snapshot_from_analysis(row,notice_id="notice",documents=[d],
        company_snapshot={},rule_version="r1",model_version="m1",
        all_documents_extracted=True)
    assert not partial.extraction_complete
    row.status="SUCCEEDED"
    absent=snapshot_from_analysis(row,notice_id="notice",documents=[d],
        company_snapshot={},rule_version="r1",model_version="m1",
        all_documents_extracted=False)
    assert not absent.extraction_complete
