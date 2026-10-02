"""Conservative Ask-back guardrail for qualification requirements.

UNKNOWN does not automatically mean "ask the user".  A question is only
askable when a short user-supplied fact can deterministically resolve the
requirement without collapsing legal/procedural logic or exceptions.
"""

from __future__ import annotations

import re
import math
from dataclasses import dataclass

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.clause_safety import is_guard_assessed, unsafe_clause_reason


@dataclass(frozen=True)
class AskabilityDecision:
    askable: bool
    reason_code: str
    reason: str


_SIMPLE_TYPES = {
    "REGION",
    "COMPANY_SIZE",
    "INDUSTRY",
    "STAFF",
    "PERFORMANCE_COUNT",
    "PERFORMANCE_AMOUNT",
    "EXPERIENCE_FIELD",
    "REGISTRATION_CERTIFICATION",
}

_SIMPLE_REGISTRATION_HINT = re.compile(
    r"(등록업체|등록된\s*업체|등록한\s*업체|등록을\s*마친|면허를?\s*보유|인증을?\s*보유|자격을?\s*보유|등록하여야|등록되어야)"
)


def classify_askability(requirement: QualificationRequirement) -> AskabilityDecision:
    """Return whether a USER_ANSWER may safely resolve an UNKNOWN requirement.

    The policy intentionally prefers false negatives over unsafe questions.
    NOT_ASKABLE remains UNKNOWN and must be resolved by evidence/profile/model
    improvements rather than by turning a complex clause into a yes/no answer.
    """

    raw = " ".join(requirement.raw.split())
    if not raw:
        return AskabilityDecision(False, "EMPTY_REQUIREMENT", "원문 조건이 비어 있습니다.")

    if requirement.type not in _SIMPLE_TYPES:
        return AskabilityDecision(False, "UNSUPPORTED_TYPE", "사용자 답변으로 해결하도록 허용하지 않은 조건 유형입니다.")

    # 추출이 가드 평가를 마친 요건은 raw 를 다시 읽지 않는다(judgment.py 와 같은 이유).
    if requirement.condition_complexity == "composite":
        return AskabilityDecision(False, str(requirement.scope.get("guard_reason") or "COMPOSITE_CONDITION"), "복합·예외·법적 절차 조건은 단순 사용자 답변으로 판정하지 않습니다.")
    code = None if is_guard_assessed(requirement.scope) else unsafe_clause_reason(raw)
    if code:
        return AskabilityDecision(False, code, "복합·예외·법적 절차 조건은 단순 사용자 답변으로 판정하지 않습니다.")

    if requirement.group_operator == "ANY_OF":
        return AskabilityDecision(False, "ALTERNATIVE_GROUP", "대안 조건 그룹은 개별 yes/no 질문으로 축약하지 않습니다.")

    if requirement.operator == "RANGE":
        return AskabilityDecision(False, "RANGE_REQUIRES_STRUCTURED_VALUE", "범위 조건은 구조화된 값을 확보한 뒤 규칙으로 판정해야 합니다.")

    numeric = requirement.type in {"STAFF", "PERFORMANCE_COUNT", "PERFORMANCE_AMOUNT"}
    if numeric and requirement.value is None:
        return AskabilityDecision(False, "STRUCTURED_VALUE_REQUIRED", "비교할 수치가 없습니다.")
    role_match = requirement.type == "STAFF" and requirement.operator == "MATCH" and requirement.scope.get("role") == requirement.value
    allowed = {">=", ">", "<=", "<", "="} if numeric and not role_match else {"MATCH", "="}
    if requirement.operator not in allowed:
        return AskabilityDecision(False, "UNSUPPORTED_OPERATOR", "규칙으로 비교할 연산자가 없거나 지원하지 않습니다.")
    if numeric and not role_match:
        try:
            valid_number = math.isfinite(float(requirement.value)) and float(requirement.value) >= 0
        except (TypeError, ValueError):
            valid_number = False
        if not valid_number:
            return AskabilityDecision(False, "STRUCTURED_VALUE_REQUIRED", "비교할 유효한 수치가 필요합니다.")

    if requirement.type == "REGISTRATION_CERTIFICATION":
        kind = str(requirement.scope.get("kind") or "")
        if kind not in {"REGISTRATION", "LICENSE", "CERTIFICATION"}:
            return AskabilityDecision(False, "REGISTRATION_KIND_UNKNOWN", "등록·면허·인증 종류가 명확하지 않습니다.")
        if not _SIMPLE_REGISTRATION_HINT.search(raw):
            return AskabilityDecision(False, "REGISTRATION_SEMANTICS_COMPLEX", "단순 보유/등록 사실로 환원할 수 없는 등록 조건입니다.")

    if requirement.type in {"STAFF", "PERFORMANCE_COUNT", "PERFORMANCE_AMOUNT"} and requirement.value is None:
        return AskabilityDecision(False, "STRUCTURED_VALUE_REQUIRED", "수치 조건인데 비교할 구조화 값이 없습니다.")

    if requirement.type in {"REGION", "COMPANY_SIZE", "INDUSTRY", "EXPERIENCE_FIELD", "REGISTRATION_CERTIFICATION"} and requirement.value in {None, ""}:
        return AskabilityDecision(False, "STRUCTURED_VALUE_REQUIRED", "비교할 구조화 값이 없습니다.")

    return AskabilityDecision(True, "ASKABLE_SIMPLE_FACT", "사용자가 알고 있는 단일 사실로 안전하게 재판정할 수 있습니다.")


def build_semantic_question(requirement: QualificationRequirement) -> str:
    """Build an ask-back question that preserves the source requirement meaning."""

    raw = " ".join(requirement.raw.split())
    value = str(requirement.value) if requirement.value not in {None, ""} else raw

    prefix = {
        "REGION": f"귀사의 사업장 소재지가 공고의 지역 조건({value})을 충족하나요?",
        "COMPANY_SIZE": f"귀사의 기업 규모가 공고 조건({value})에 해당하나요?",
        "INDUSTRY": f"귀사가 공고에서 요구한 업종({value})으로 등록되어 있나요?",
        "STAFF": "귀사의 현재 인력 현황이 다음 공고 조건을 충족하나요?",
        "PERFORMANCE_COUNT": "귀사의 수행실적 건수가 다음 공고 조건을 충족하나요?",
        "PERFORMANCE_AMOUNT": "귀사의 수행실적 금액이 다음 공고 조건을 충족하나요?",
        "EXPERIENCE_FIELD": f"귀사에 공고가 요구한 경험 분야({value})의 수행 경험이 있나요?",
        "REGISTRATION_CERTIFICATION": f"귀사가 공고에서 요구한 등록·면허·인증({value})을 보유하고 있나요?",
    }.get(requirement.type, "다음 공고 조건을 충족하나요?")

    # Raw source semantics are intentionally retained in the question itself so
    # a short canonical value can never silently replace the original clause.
    return f"{prefix} — 원문 조건: {raw}"
