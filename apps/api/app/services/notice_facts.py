"""Normalize version-scoped G2B facts and compare them without an LLM."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NoticeFact


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _integer(value: Any) -> int | None:
    normalized = _text(value)
    if normalized is None:
        return None
    try:
        return int(Decimal(normalized.replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def facts_from_g2b_item(item: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []

    deadline = _text(item.get("bidClseDt"))
    if deadline is not None:
        facts.append(
            {
                "fact_key": "SUBMISSION_DEADLINE",
                "value_json": {"at": deadline},
                "source_field": "bidClseDt",
                "raw_value": deadline,
            }
        )

    budget_field = "asignBdgtAmt" if _text(item.get("asignBdgtAmt")) else "bdgtAmt"
    budget_raw = _text(item.get(budget_field))
    budget = _integer(budget_raw)
    if budget is not None:
        facts.append(
            {
                "fact_key": "BUDGET_AMOUNT",
                "value_json": {"amount": budget, "currency": "KRW"},
                "source_field": budget_field,
                "raw_value": budget_raw,
            }
        )

    agency_code = _text(item.get("dminsttCd")) or _text(item.get("ntceInsttCd"))
    agency_name = _text(item.get("dminsttNm")) or _text(item.get("ntceInsttNm"))
    if agency_code is not None or agency_name is not None:
        facts.append(
            {
                "fact_key": "ORDERING_AGENCY",
                "value_json": {"code": agency_code, "name": agency_name},
                "source_field": "dminsttCd,dminsttNm",
                "raw_value": agency_name or agency_code,
            }
        )

    joint_method = _text(item.get("cmmnSpldmdMethdNm"))
    if joint_method is not None:
        status = "not_allowed" if "불허" in joint_method else "allowed"
        facts.append(
            {
                "fact_key": "JOINT_SUPPLY",
                "value_json": {
                    "status": status,
                    "method_code": _text(item.get("cmmnSpldmdMethdCd")),
                    "method_name": joint_method,
                },
                "source_field": "cmmnSpldmdMethdCd,cmmnSpldmdMethdNm",
                "raw_value": joint_method,
            }
        )

    return facts


def upsert_g2b_notice_facts(
    db: Session,
    *,
    notice_version_id: UUID,
    item: dict[str, Any],
    updated_at: datetime,
) -> None:
    existing = {
        fact.fact_key: fact
        for fact in db.scalars(
            select(NoticeFact).where(NoticeFact.notice_version_id == notice_version_id)
        ).all()
    }
    for values in facts_from_g2b_item(item):
        fact = existing.get(values["fact_key"])
        if fact is None:
            db.add(
                NoticeFact(
                    notice_version_id=notice_version_id,
                    source_type="G2B_API",
                    updated_at=updated_at,
                    **values,
                )
            )
            continue
        if fact.source_type != "G2B_API":
            continue
        fact.value_json = values["value_json"]
        fact.source_field = values["source_field"]
        fact.raw_value = values["raw_value"]
        fact.updated_at = updated_at


def diff_notice_facts(
    baseline: list[NoticeFact],
    current: list[NoticeFact],
    *,
    include_unchanged: bool = False,
) -> list[dict[str, Any]]:
    baseline_by_key = {fact.fact_key: fact for fact in baseline}
    current_by_key = {fact.fact_key: fact for fact in current}
    changes: list[dict[str, Any]] = []
    for fact_key in sorted(set(baseline_by_key) | set(current_by_key)):
        before = baseline_by_key.get(fact_key)
        after = current_by_key.get(fact_key)
        if before is None:
            change_type = "ADDED"
        elif after is None:
            change_type = "REMOVED"
        elif before.value_json == after.value_json:
            change_type = "UNCHANGED"
        else:
            change_type = "MODIFIED"
        if include_unchanged or change_type != "UNCHANGED":
            changes.append(
                {
                    "fact_key": fact_key,
                    "change_type": change_type,
                    "baseline": before,
                    "current": after,
                }
            )
    return changes
