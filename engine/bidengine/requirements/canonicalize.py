"""Canonicalization pipeline for validated legacy extraction slots."""

from __future__ import annotations

from typing import Any

from bidengine.contracts import Evidence, QualificationRequirement
from bidengine.grounding.evidence_adapter import build_evidence_from_slot
from bidengine.requirements.deduplicate import deduplicate_requirements
from bidengine.ports import IndustryNameResolver
from bidengine.requirements.legacy_slots import adapt_legacy_slot


def canonicalize_validated_slot(
    slot: dict[str, Any],
    *,
    notice_version_id: str,
    key_prefix: str,
    source_type: str = "NOTICE_DOCUMENT",
    case_id: str | None = None,
    industry_resolver: IndustryNameResolver | None = None,
) -> tuple[list[QualificationRequirement], list[Evidence], list[dict[str, Any]]]:
    """Convert one source-grounded legacy slot to canonical objects.

    One extracted slot may become multiple atomic requirements, but they all point
    to the same source-grounded Evidence item unless a later extractor supplies
    finer-grained provenance.
    """
    requirements, diagnostics = adapt_legacy_slot(
        slot,
        notice_version_id=notice_version_id,
        key_prefix=key_prefix,
        industry_resolver=industry_resolver,
    )
    if slot.get("_salvaged_codes"):
        # 모델이 빠뜨려 코드가 원문에서 채운 슬롯. 요건은 정상 경로로 만들어졌고, 빠뜨렸다는
        # 사실만 남긴다 — 이 진단이 많이 찍히면 모델 쪽이 흔들린다는 신호다.
        diagnostics.append({
            "code": "INDUSTRY_CODE_SALVAGED_FROM_SOURCE",
            "raw": slot.get("raw") or "",
            "codes": list(slot["_salvaged_codes"]),
        })
    evidence_key = f"{key_prefix}-EVD"
    evidence = build_evidence_from_slot(
        slot,
        evidence_key=evidence_key,
        source_type=source_type,
        notice_version_id=notice_version_id,
        case_id=case_id,
    )

    if not requirements:
        # A notice fact that cannot be mapped to the closed qualification
        # taxonomy still needs traceable source evidence in the API response.
        return (
            [],
            [evidence],
            [{**item, "evidence_keys": [evidence_key]} for item in diagnostics],
        )

    linked_requirements: list[QualificationRequirement] = []
    for requirement in requirements:
        linked_requirements.append(
            requirement.model_copy(update={"evidence_keys": [evidence_key]})
        )

    return (
        linked_requirements,
        [evidence],
        [{**item, "evidence_keys": [evidence_key]} for item in diagnostics],
    )


def canonicalize_validated_slots(
    slots: list[dict[str, Any]],
    *,
    notice_version_id: str,
    source_type: str = "NOTICE_DOCUMENT",
    case_id: str | None = None,
    key_prefix: str = "REQ",
    industry_resolver: IndustryNameResolver | None = None,
) -> dict[str, Any]:
    """Canonicalize multiple accepted slots with stable per-slot keys."""
    requirements: list[QualificationRequirement] = []
    evidence: list[Evidence] = []
    diagnostics: list[dict[str, Any]] = []
    source_chunk_by_key: dict[str, str | None] = {}

    for index, slot in enumerate(slots, start=1):
        slot_prefix = f"{key_prefix}-{index:03d}"
        slot_requirements, slot_evidence, slot_diagnostics = canonicalize_validated_slot(
            slot,
            notice_version_id=notice_version_id,
            key_prefix=slot_prefix,
            source_type=source_type,
            case_id=case_id,
            industry_resolver=industry_resolver,
        )
        requirements.extend(slot_requirements)
        evidence.extend(slot_evidence)
        diagnostics.extend(slot_diagnostics)
        for requirement in slot_requirements:
            source_chunk_by_key[requirement.requirement_key] = slot.get("_source_chunk_id")

    # 슬롯 하나만 봐서는 겹침을 알 수 없다. 모델이 같은 조항을 두 슬롯으로 나눠 서로
    # 다른 유형을 붙이면, 둘은 ALL_OF 묶음이 되어 자격 있는 회사를 떨어뜨린다.
    requirements, overlap_diagnostics = deduplicate_requirements(
        requirements, source_chunk_by_key=source_chunk_by_key
    )
    kept_evidence_keys = {
        key for requirement in requirements for key in requirement.evidence_keys
    }
    for item in overlap_diagnostics:
        # 접힌 요건의 근거도 응답에 남아 있어야 담당자가 무엇이 접혔는지 볼 수 있다.
        item.setdefault("evidence_keys", sorted(kept_evidence_keys))
    diagnostics.extend(overlap_diagnostics)

    return {
        "requirements": requirements,
        "evidence": evidence,
        "diagnostics": diagnostics,
    }
