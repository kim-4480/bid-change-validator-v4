from types import SimpleNamespace

from bidengine.contracts import Evidence, EvidenceLocation, QualificationRequirement
from bideval.golden.spans import GoldenSpan
from bideval.scoring import score_case


def chunk(text, doc="doc"):
    return {"chunk_id": "c", "text": text, "source_blocks": [{"document_id": doc}]}


def span(**kwargs):
    return GoldenSpan(span_id="s", document_id="doc", span_kind="POSITIVE",
                      quote="업종 등록", **kwargs)


def test_whitespace_and_document_scoping():
    c = chunk("업종등록")
    assert score_case([span()], [c], [c])["metrics"]["selection_recall"]["value"] == 1
    wrong = chunk("업종등록", "other")
    assert score_case([span()], [wrong], [wrong])["metrics"]["selection_recall"]["value"] == 0


def test_truncation_is_not_selection_success():
    chunks = [chunk("x" * 32_000), chunk("업종 등록")]
    report = score_case([span()], chunks, chunks)
    assert report["metrics"]["selection_recall"]["value"] == 1
    assert report["metrics"]["context_recall"]["value"] == 0
    assert report["context"]["truncated_chars"] > 0


def test_split_span_and_empty_denominator():
    chunks = [chunk("업종"), chunk("등록")]
    assert score_case([span()], chunks, chunks)["metrics"]["span_containment"]["value"] == 0
    report = score_case([], [], [])
    assert report["metrics"]["selection_recall"]["value"] is None
    assert report["drop_rate"]["value"] is None


def test_canonical_requires_linked_source_and_exact_null_scope_group():
    label = span(expected={"unit": None, "scope": {"kind": "REGISTRATION"}, "group_operator": "ALL_OF"})
    evidence = Evidence(evidence_key="e", source_type="NOTICE_DOCUMENT", document_id="doc",
                        notice_version_id="v", location=EvidenceLocation(), quote="업종 등록")
    req = QualificationRequirement(requirement_key="r", notice_version_id="v", type="INDUSTRY",
                                   raw="업종 등록", scope={"kind": "REGISTRATION"},
                                   group_operator="ALL_OF", evidence_keys=["e"])
    def match(r=req, e=evidence):
        result = SimpleNamespace(evidence=[e], requirements=[r], status="SUCCEEDED")
        return score_case([label], [], [], result)["spans"][0]["canonical_match"]
    assert match()
    assert not match(req.model_copy(update={"unit": "CODE"}))
    assert not match(req.model_copy(update={"scope": {}}))
    assert not match(req.model_copy(update={"group_operator": "ANY_OF"}))
    assert not match(e=evidence.model_copy(update={"document_id": "other"}))
    assert not match(req.model_copy(update={"evidence_keys": []}))


def test_trap_denominator_is_labeled_traps():
    label = GoldenSpan(span_id="trap", document_id="doc", span_kind="TRAP", quote="사후 제재")
    c = chunk("사후 제재")
    metric = score_case([label], [c], [c])["metrics"]["trap_selection_rate"]
    assert metric == {"numerator": 1, "denominator": 1, "value": 1, "reason": None}
