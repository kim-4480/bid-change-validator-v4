"""Changed-notice impacts: fail closed on uncertain lineage and evidence."""
import json
from pathlib import Path

import pytest
from bidengine.contracts import Judgment, QualificationRequirement
from bidengine.diff.impact_plan import AnalysisSnapshot, plan_requirement_impacts

def req(key, version, value, kind="INDUSTRY", group=None, raw=None):
    return QualificationRequirement(
        requirement_key=key, notice_version_id=version, type=kind,
        operator="MATCH", value=value, raw=raw or f"registration {value}",
        requirement_group_key=group, group_operator="ANY_OF" if group else None,
        evidence_keys=[f"EV-{version}-{key}"], scope={"guard": "assessed"})

def judgment(r, status="SATISFIED", rule_version="rules-v1"):
    return Judgment(
        judgment_key="J-"+r.requirement_key, preflight_case_id="CASE",
        notice_version_id=r.notice_version_id, requirement_key=r.requirement_key,
        status=status, basis_type="PROFILE",
        reason_code="RULE_MATCH" if status != "UNKNOWN" else "NEEDS_REVIEW",
        rule_version=rule_version)

def plan(before, after, *, company="company-v1", old_doc="old", new_doc="new",
         complete=True, grounded=None, previous=None):
    return plan_requirement_impacts(
        before, after,
        baseline_snapshot=AnalysisSnapshot("notice", "v1", old_doc, "company-v1", "rules-v1", True, "run-v1", "input-v1", "input-v1", "model-v1", True, "2026-10-09"),
        current_snapshot=AnalysisSnapshot("notice", "v2", new_doc, company, "rules-v1", complete, "run-v2", "input-v2", "input-v2", "model-v1", True, "2026-10-09"),
        previous_judgments=previous if previous is not None else {r.requirement_key: judgment(r) for r in before},
        grounded_current_keys=grounded if grounded is not None else {r.requirement_key for r in after})

def test_changed_recalculates_but_unaffected_is_reusable():
    before = [req("A", "v1", "1169"), req("B", "v1", "Seoul", "REGION")]
    after = [req("A2", "v2", "1169"), req("B", "v2", "Gangwon", "REGION")]
    impacts = plan(before, after)
    assert {x.current_key: x.action for x in impacts} == {"A2": "REUSE", "B": "RECALCULATE"}
    assert next(x for x in impacts if x.current_key == "A2").baseline_judgment is not None

@pytest.mark.parametrize("options", [{"company":"changed"}, {"old_doc":None}, {"complete":False}])
def test_lineage_change_never_reuses(options):
    assert plan([req("A","v1","1169")], [req("B","v2","1169")], **options)[0].action != "REUSE"

def test_unverified_current_evidence_requires_review():
    assert plan([req("A","v1","1169")], [req("B","v2","1169")], grounded=set())[0].action == "REVIEW"

def test_unknown_prior_is_not_carried_forward():
    before=[req("A","v1","1169")]
    assert plan(before,[req("A","v2","1169")],previous={"A":judgment(before[0],"UNKNOWN")})[0].action == "RECALCULATE"

def test_any_of_group_change_recalculates_all_alternatives():
    before=[req("A","v1","1169",group="G"),req("B","v1","1170",group="G")]
    after=[req("A","v2","1169",group="G"),req("B","v2","1180",group="G")]
    assert [item.action for item in plan(before,after)] == ["RECALCULATE","RECALCULATE"]

def test_same_document_conflicting_extractions_are_for_review():
    assert plan([req("A","v1","1169")],[req("A","v2","1170")],old_doc="same",new_doc="same")[0].action=="REVIEW"

def test_incomplete_extraction_cannot_retire_missing_requirement():
    assert plan([req("A","v1","1169")],[],complete=False)[0].action=="REVIEW"

def test_duplicate_and_wrong_version_rejected():
    before=[req("A","v1","1169")]
    after=[req("A","v2","1169")]
    with pytest.raises(ValueError,match="duplicate"):
        plan(before+before,after)
    with pytest.raises(ValueError,match="different source version"):
        plan(before,before)

def test_real_g2_observation_before_after_is_provisional():
    root=Path(__file__).resolve().parents[2]
    data=json.loads((root/"eval/golden/qualification-real-v0.1/cases/G2/observations/source-change.json").read_text(encoding="utf-8"))
    assert data["review_status"]=="DRAFT" and data["not_ground_truth"] is True
    assert "강원도에 있는 업체" in data["qualification_before"]
    assert "강원도에 있는 업체" not in data["qualification_after"]
    before=[req("R","v1","Gangwon","REGION",raw=data["quote"]),req("I","v1","1169")]
    after=[req("I2","v2","1169")]
    assert {x.action for x in plan(before,after)}=={"RETIRE","REUSE"}

def test_missing_analysis_input_fingerprint_blocks_reuse_and_retirement():
    before = [req("A", "v1", "1169")]
    after = [req("B", "v2", "1169")]
    a = AnalysisSnapshot("notice", "v1", "old", "company", "rules", True)
    b = AnalysisSnapshot("notice", "v2", "new", "company", "rules", True)
    impacts = plan_requirement_impacts(before, after, baseline_snapshot=a,
                                       current_snapshot=b, previous_judgments={},
                                       grounded_current_keys={"B"})
    assert impacts[0].action == "REVIEW"
    removed = plan_requirement_impacts(before, [], baseline_snapshot=a,
                                       current_snapshot=b, previous_judgments={},
                                       grounded_current_keys=set())
    assert removed[0].action == "REVIEW"

def test_same_source_disappearance_does_not_retire():
    assert plan([req("A", "v1", "1169")], [], old_doc="same", new_doc="same")[0].action == "REVIEW"

def test_removed_or_branch_invalidates_surviving_member():
    before = [req("A", "v1", "1169", group="G"), req("B", "v1", "1170", group="G")]
    after = [req("A", "v2", "1169", group="G")]
    actions = {x.current_key or x.baseline_key: x.action for x in plan(before, after)}
    assert actions == {"A": "RECALCULATE", "B": "RETIRE"}
