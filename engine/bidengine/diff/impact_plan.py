"""Fail-closed source-versioned selective changed-notice revalidation planner.

No database writes. REUSE refers to the prior decision only; the caller must
create a new decision identity and cite evidence validated against current text.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Mapping
from bidengine.contracts import Judgment, QualificationRequirement
from bidengine.diff.requirement_diff import diff_requirements

ImpactAction = Literal["REUSE", "RECALCULATE", "REVIEW", "RETIRE"]

@dataclass(frozen=True, slots=True)
class AnalysisSnapshot:
    notice_id: str
    notice_version_id: str
    document_fingerprint: str | None
    company_snapshot_fingerprint: str | None
    rule_version: str | None
    extraction_complete: bool = True
    analysis_run_id: str | None = None
    input_fingerprint: str | None = None
    verified_input_fingerprint: str | None = None
    model_version: str | None = None
    verdict_complete: bool = False
    reference_date: str | None = None

@dataclass(frozen=True, slots=True)
class RequirementImpact:
    action: ImpactAction
    reason: str
    baseline_key: str | None
    current_key: str | None
    baseline_judgment: Judgment | None = None

def plan_requirement_impacts(
    baseline: list[QualificationRequirement],
    current: list[QualificationRequirement],
    *,
    baseline_snapshot: AnalysisSnapshot,
    current_snapshot: AnalysisSnapshot,
    previous_judgments: Mapping[str, Judgment],
    grounded_current_keys: set[str],
) -> list[RequirementImpact]:
    """Only reuse unchanged conditions with verified lineage and current evidence."""
    if not baseline_snapshot.notice_id or baseline_snapshot.notice_id != current_snapshot.notice_id:
        raise ValueError("notice identities must match")
    if (not baseline_snapshot.notice_version_id or not current_snapshot.notice_version_id
            or baseline_snapshot.notice_version_id == current_snapshot.notice_version_id):
        raise ValueError("distinct and nonempty notice version identities required")
    for requirements, snapshot in ((baseline, baseline_snapshot), (current, current_snapshot)):
        keys = [req.requirement_key for req in requirements]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate requirement keys")
        if any(req.notice_version_id != snapshot.notice_version_id for req in requirements):
            raise ValueError("requirement belongs to a different source version")
    changes = diff_requirements(baseline, current)
    changed_groups = {
        change.current.requirement_group_key for change in changes
        if change.change_type in {"ADDED", "MODIFIED"}
        and change.current is not None and change.current.requirement_group_key
    }
    changed_groups.update(
        change.baseline.requirement_group_key for change in changes
        if change.change_type in {"REMOVED", "MODIFIED"}
        and change.baseline is not None and change.baseline.requirement_group_key
    )
    lineage_verified = all(
        snapshot.analysis_run_id and snapshot.input_fingerprint
        and snapshot.verified_input_fingerprint
        and snapshot.input_fingerprint == snapshot.verified_input_fingerprint
        for snapshot in (baseline_snapshot, current_snapshot)
    )
    complete = (
        baseline_snapshot.extraction_complete and current_snapshot.extraction_complete
        and bool(lineage_verified)
        and baseline_snapshot.verdict_complete and current_snapshot.verdict_complete
    )
    lineage_safe = (
        complete and bool(baseline_snapshot.document_fingerprint)
        and bool(current_snapshot.document_fingerprint)
        and bool(baseline_snapshot.company_snapshot_fingerprint)
        and baseline_snapshot.company_snapshot_fingerprint == current_snapshot.company_snapshot_fingerprint
        and bool(baseline_snapshot.rule_version)
        and baseline_snapshot.rule_version == current_snapshot.rule_version
        and bool(baseline_snapshot.model_version)
        and baseline_snapshot.model_version == current_snapshot.model_version
        and bool(baseline_snapshot.reference_date)
        and baseline_snapshot.reference_date == current_snapshot.reference_date
    )
    same_document = (
        bool(baseline_snapshot.document_fingerprint)
        and baseline_snapshot.document_fingerprint == current_snapshot.document_fingerprint
    )
    impacts: list[RequirementImpact] = []
    for change in changes:
        old, new = change.baseline, change.current
        if new is None:
            impacts.append(RequirementImpact(
                "RETIRE" if complete and not same_document else "REVIEW",
                "requirement_removed" if complete and not same_document else ("same_source_conflicting_extractions" if same_document else "unverified_analysis_lineage"),
                change.baseline_key, None))
            continue
        if not complete:
            action, reason = "REVIEW", "unverified_analysis_lineage_or_incomplete_extraction"
        elif same_document and change.change_type != "UNCHANGED":
            action, reason = "REVIEW", "same_source_conflicting_extractions"
        elif change.change_type != "UNCHANGED":
            action, reason = "RECALCULATE", "requirement_changed"
        elif new.requirement_group_key in changed_groups:
            action, reason = "RECALCULATE", "logical_group_changed"
        elif new.requirement_key not in grounded_current_keys or not new.evidence_keys:
            action, reason = "REVIEW", "current_source_evidence_unverified"
        elif not lineage_safe:
            action, reason = "RECALCULATE", "lineage_or_company_changed"
        else:
            previous = previous_judgments.get(change.baseline_key or "")
            if (previous is None or old is None
                    or previous.requirement_key != old.requirement_key
                    or previous.notice_version_id != baseline_snapshot.notice_version_id
                    or previous.rule_version != baseline_snapshot.rule_version
                    or previous.status == "UNKNOWN"
                    or previous.basis_type != "PROFILE"):
                action, reason = "RECALCULATE", "prior_verdict_not_reusable"
            else:
                action, reason = "REUSE", "verified_unchanged_condition"
        previous = previous_judgments.get(change.baseline_key or "") if action == "REUSE" else None
        impacts.append(RequirementImpact(action, reason, change.baseline_key, change.current_key, previous))
    return impacts
