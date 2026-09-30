"""Read a company impact only from a fully linked saved revalidation."""

from collections import Counter
import hashlib
import json

from sqlalchemy import select

from ..judgment_models import QualificationJudgmentRun
from bidengine.judgment.rules import RULE_VERSION
from ..revalidation_models import QualificationRevalidationRun


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def compare_saved_impact(lineage, before, after, provenance, changes):
    if lineage is None:
        return _unavailable("현재 판정과 연결된 재검증 실행 기록이 없어 전후 영향을 단정할 수 없습니다.")
    if before is None or after is None:
        return _unavailable("재검증의 기준 또는 결과 판정이 없어 전후 영향을 비교할 수 없습니다.")
    expected = (
        lineage.preflight_case_id == provenance.case_id,
        lineage.source_judgment_run_id == before.id == provenance.baseline.judgment_run_id,
        lineage.result_judgment_run_id == after.id == provenance.current.judgment_run_id,
        lineage.baseline_analysis_run_id == before.analysis_run_id == provenance.baseline.analysis_run_id,
        lineage.current_analysis_run_id == after.analysis_run_id == provenance.current.analysis_run_id,
        before.notice_version_id == provenance.baseline.notice_version_id,
        after.notice_version_id == provenance.current.notice_version_id,
        before.analysis_status == provenance.baseline.analysis_status,
        after.analysis_status == provenance.current.analysis_status,
    )
    if not all(expected) or any(
        run.preflight_case_id != provenance.case_id or run.company_id != provenance.company_id
        for run in (before, after)
    ):
        return _unavailable("재검증 기록이 현재 사례·회사·공고 버전·분석·판정과 일치하지 않습니다.")
    if before.rule_version != after.rule_version or after.rule_version != RULE_VERSION:
        return _unavailable("전후 판정의 규칙이 달라 공고 변경만의 영향으로 비교할 수 없습니다.")
    if before.reference_date != after.reference_date:
        return _unavailable("전후 판정의 기준일이 달라 공고 변경만의 영향으로 비교할 수 없습니다.")
    if (
        not before.profile_snapshot
        or before.profile_snapshot != after.profile_snapshot
        or before.profile_snapshot.get("company_id") != str(provenance.company_id)
    ):
        return _unavailable("전후 판정에 사용한 회사정보가 달라 공고 변경만의 영향으로 비교할 수 없습니다.")

    old = {item.requirement_key: item for item in before.judgments}
    new = {item.requirement_key: item for item in after.judgments}
    if (
        len(old) != len(before.judgments)
        or len(new) != len(after.judgments)
        or set(old) != {item.baseline_key for item in changes if item.baseline_key}
        or set(new) != {item.current_key for item in changes if item.current_key}
    ):
        return _unavailable("전후 요건과 판정의 연결이 불완전하여 영향 비교를 보류합니다.")

    rows = []
    for change in changes:
        before_judgment = old.get(change.baseline_key)
        after_judgment = new.get(change.current_key)
        requirement = change.current or change.baseline
        rows.append({
            "raw": requirement.raw,
            "change_type": change.change_type,
            "before_value": change.baseline.value if change.baseline else None,
            "after_value": change.current.value if change.current else None,
            "before_status": before_judgment.status if before_judgment else None,
            "after_status": after_judgment.status if after_judgment else None,
            "revalidated": bool(change.current_key in lineage.revalidated_keys),
        })
    return {
        "available": True,
        "lineage_id": str(lineage.id),
        "reference_date": str(after.reference_date),
        "rule_version": after.rule_version,
        "profile_sha256": hashlib.sha256(
            json.dumps(before.profile_snapshot, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "before_status": before.overall_status,
        "after_status": after.overall_status,
        "before_counts": dict(Counter(item.status for item in before.judgments)),
        "after_counts": dict(Counter(item.status for item in after.judgments)),
        "partial": before.analysis_status == "PARTIAL" or after.analysis_status == "PARTIAL",
        "rows": rows,
    }


def read_change_impact(db, change_result):
    provenance = change_result.provenance
    with db.no_autoflush:
        lineage = db.scalar(
            select(QualificationRevalidationRun)
            .where(
                QualificationRevalidationRun.preflight_case_id == provenance.case_id,
                QualificationRevalidationRun.result_judgment_run_id == provenance.current.judgment_run_id,
            )
            .order_by(
                QualificationRevalidationRun.created_at.desc(),
                QualificationRevalidationRun.id.desc(),
            )
            .limit(1)
        )
        before = db.get(QualificationJudgmentRun, lineage.source_judgment_run_id) if lineage else None
        after = db.get(QualificationJudgmentRun, lineage.result_judgment_run_id) if lineage else None
        return compare_saved_impact(lineage, before, after, provenance, change_result.changes)


STATUS = {
    "SATISFIED": "충족",
    "UNSATISFIED": "미달",
    "UNKNOWN": "확인 필요",
    "eligible": "참가 가능",
    "ineligible": "참가 불가",
    "insufficient_data": "판정 보류",
    None: "해당 요건 없음",
}


def impact_text(impact: dict) -> str:
    if not impact["available"]:
        return impact["reason"]
    lines = [
        f"저장된 재검증의 전후 판정: {STATUS[impact['before_status']]} → {STATUS[impact['after_status']]}",
        "두 판정은 같은 회사정보 snapshot·규칙·기준일을 사용했습니다. 현재 회사정보를 새로 검증한 것은 아닙니다.",
    ]
    for row in impact["rows"]:
        lines.append(
            f"요건: {row['raw']} / 비교값: {row['before_value']} → {row['after_value']} / "
            f"판정: {STATUS[row['before_status']]} → {STATUS[row['after_status']]} / "
            + ("이번 재검증에서 다시 판정함" if row["revalidated"] else "기준 판정을 이어받았거나 삭제된 요건")
        )
    if impact["partial"]:
        lines.append("분석이 부분 완료이므로 전체 참가자격의 법적 확정이 아닙니다.")
    return "\n".join(lines)
