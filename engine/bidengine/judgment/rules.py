"""Deterministic qualification judgment over canonical requirements and company facts.

The LLM is not used in this layer. Requirement extraction produces canonical
operands; this module compares them against a frozen company-profile snapshot.

A missing fact is not automatically a negative fact. Collection-backed profile
areas (staff roles, performances, certifications) carry explicit completeness
flags so an absent item can remain UNKNOWN until the user confirms the profile.
"""

from __future__ import annotations

import calendar
import math
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from bidengine.contracts import Judgment, QualificationRequirement
from bidengine.judgment.clause_safety import GUARD_REASON_EXCEPTION, is_guard_assessed, unsafe_clause_reason
from bidengine.normalization.regions import region_name_relation


RULE_VERSION = "qualification-rules-v0.3"
OverallQualificationStatus = Literal["eligible", "ineligible", "insufficient_data"]


class ProfileCompleteness(BaseModel):
    region: bool = True
    company_size: bool = True
    industries: bool = True
    staff_total: bool = True
    staff_roles: bool = False
    performances: bool = False
    certifications: bool = False


class ProfileIndustryFact(BaseModel):
    code: str
    name: str
    verified: bool = False


class ProfileStaffRoleFact(BaseModel):
    role_name: str
    headcount: int = Field(ge=0)
    career_years: float | None = Field(default=None, ge=0)
    verified: bool = False


class ProfileStaffFact(BaseModel):
    total_count: int = Field(ge=0)
    verified: bool = False
    roles: list[ProfileStaffRoleFact] = Field(default_factory=list)


class ProfilePerformanceFact(BaseModel):
    ref: str
    name: str
    client_name: str | None = None
    client_institution_code: str | None = None
    amount: int = Field(ge=0)
    started_at: date | None = None
    completed_at: date | None = None
    completed_year: int | None = Field(default=None, ge=1900, le=2100)
    fields: list[str] = Field(default_factory=list)
    verified: bool = False


class ProfileCertificationFact(BaseModel):
    ref: str
    name: str
    certification_code: str | None = None
    issuer_name: str | None = None
    issued_at: date | None = None
    expires_at: date | None = None
    verified: bool = False


class CompanyProfileSnapshot(BaseModel):
    company_id: str
    region_code: str | None = None
    region_name: str | None = None
    company_size: str | None = None
    industries: list[ProfileIndustryFact] = Field(default_factory=list)
    staff: ProfileStaffFact | None = None
    performances: list[ProfilePerformanceFact] = Field(default_factory=list)
    certifications: list[ProfileCertificationFact] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)
    completeness: ProfileCompleteness = Field(default_factory=ProfileCompleteness)


class JudgmentEvaluation(BaseModel):
    judgments: list[Judgment]
    overall_status: OverallQualificationStatus


_EVIDENCE_REQUIRED_TYPES = {
    "PERFORMANCE_AMOUNT",
    "PERFORMANCE_COUNT",
    "INDUSTRY",
    "STAFF",
    "REGISTRATION_CERTIFICATION",
    "EXPERIENCE_FIELD",
}

_COMPANY_SIZE_ALIASES: dict[str, set[str]] = {
    "소상공인": {"MICRO"},
    "소기업": {"MICRO", "SMALL"},
    # "중기업·소기업 또는 소상공인" — 중기업이 없으면 이 문장이 '소기업' 으로 좁혀져 중기업 회사가 미달이 된다
    # (2026-10-06 무작위 표본). 합집합 중기업∪소기업∪소상공인 = 중소기업.
    "중기업": {"MEDIUM"},
    "중소기업": {"MICRO", "SMALL", "MEDIUM"},
    "중견기업": {"MID_SIZED"},
    "대기업": {"LARGE"},
}


def _norm(value: object | None) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s\-_./(),]+", "", str(value).casefold())


def _profile_ref(kind: str, field: str, value: object) -> dict[str, str]:
    return {"kind": kind, "field": field, "value": str(value)}


def _requires_evidence(requirement: QualificationRequirement) -> bool:
    return requirement.type in _EVIDENCE_REQUIRED_TYPES


def _judgment(
    *,
    requirement: QualificationRequirement,
    preflight_case_id: str,
    status: Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"],
    basis_type: Literal["PROFILE", "USER_ANSWER", "NONE"],
    evidence_held: bool = False,
    reason_code: Literal[
        "RULE_MATCH",
        "RULE_MISMATCH",
        "INSUFFICIENT_DATA",
        "NEEDS_REVIEW",
        "UNSUPPORTED_REQUIREMENT",
    ],
    profile_refs: list[dict[str, str]] | None = None,
    rule_version: str = RULE_VERSION,
) -> Judgment:
    return Judgment(
        judgment_key=f"JUDG:{preflight_case_id}:{requirement.requirement_key}",
        preflight_case_id=preflight_case_id,
        notice_version_id=requirement.notice_version_id,
        requirement_key=requirement.requirement_key,
        status=status,
        basis_type=basis_type,
        evidence_held=evidence_held,
        reason_code=reason_code,
        requires_evidence=_requires_evidence(requirement),
        profile_refs=list(profile_refs or []),
        requirement_evidence_keys=list(requirement.evidence_keys),
        rule_version=rule_version,
    )


def _unknown(
    requirement: QualificationRequirement,
    preflight_case_id: str,
    *,
    unsupported: bool = False,
) -> Judgment:
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNKNOWN",
        basis_type="NONE",
        reason_code="UNSUPPORTED_REQUIREMENT" if unsupported else "INSUFFICIENT_DATA",
    )


# 미달(UNSATISFIED)은 닫힌 값끼리 비교했을 때만 낸다: 코드, 마스터 공식 명칭, 행정구역 위계,
# 기업 규모 별칭표, 숫자, 날짜. 경험분야·발주처·역할명·인증명처럼 통제 어휘가 없는 자유
# 문자열이 안 맞은 것은 "다르다"가 아니라 "같은지 모른다"이므로 확인 필요로 돌리고, 사용자가
# 판단할 수 있게 비교한 회사 쪽 표현을 함께 남긴다 (ADR 0001 문제 4).
NEGATIVE_VERDICT_BASIS: dict[str, str] = {
    "REGION": "행정구역 위계",
    "COMPANY_SIZE": "기업 규모 별칭표 (표에 없는 표현은 확인 필요)",
    "INDUSTRY": "업종 코드 또는 마스터 공식 명칭",
    "STAFF": "인원 수 (역할명 불일치는 확인 필요)",
    "PERFORMANCE_AMOUNT": "금액·기간 (분야·발주처 불일치는 확인 필요)",
    "PERFORMANCE_COUNT": "건수·기간 (분야·발주처 불일치는 확인 필요)",
    "EXPERIENCE_FIELD": "기간 안 실적 부재 (분야 불일치는 확인 필요)",
    "REGISTRATION_CERTIFICATION": "코드·유효기간 (이름·발급기관 불일치는 확인 필요)",
}


def _vocabulary_unknown(
    requirement: QualificationRequirement,
    preflight_case_id: str,
    compared: list[tuple[str, str, object]],
) -> Judgment:
    """자유 문자열이 안 맞아 미달을 확정하지 않은 판정. 비교한 회사 쪽 표현을 근거로 남긴다."""
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNKNOWN",
        basis_type="NONE",
        reason_code="NEEDS_REVIEW",
        profile_refs=[_profile_ref("vocabulary", "required", requirement.value if requirement.value is not None
                                   else requirement.scope.get("experience_field") or requirement.scope.get("role") or "")]
        + [_profile_ref(kind, field, value) for kind, field, value in compared],
    )


def _compare_number(observed: float, operator: str | None, expected: object | None) -> bool | None:
    try:
        target = float(expected)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(target) or not math.isfinite(observed):
        return None
    if operator == ">=":
        return observed >= target
    if operator == ">":
        return observed > target
    if operator == "<=":
        return observed <= target
    if operator == "<":
        return observed < target
    if operator in {"=", "MATCH"}:
        return observed == target
    return None


def _compare_range(observed: float, scope: dict[str, object]) -> bool | None:
    minimum = scope.get("min")
    maximum = scope.get("max")
    min_operator = str(scope.get("min_operator") or ">=")
    max_operator = str(scope.get("max_operator") or "<=")

    if minimum is not None:
        lower = _compare_number(observed, min_operator, minimum)
        if lower is None:
            return None
        if not lower:
            return False
    if maximum is not None:
        upper = _compare_number(observed, max_operator, maximum)
        if upper is None:
            return None
        if not upper:
            return False
    return True if minimum is not None or maximum is not None else None


def _subtract_months(day: date, months: float | int) -> date:
    count = max(0, int(round(float(months))))
    absolute = day.year * 12 + day.month - 1 - count
    year, month0 = divmod(absolute, 12)
    month = month0 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def _string_match(observed: str, expected: object | None) -> bool:
    left = _norm(observed)
    right = _norm(expected)
    if not left or not right:
        return False
    return left == right or right in left or left in right


_NAME_TOKEN_RE = re.compile(r"[0-9]+|[A-Za-z]+|[가-힣]+")


def _certification_match(held_name: str, required_name: object | None) -> bool:
    """Match a held certification against a required one, tolerating punctuation.

    `_string_match` alone reports a company that holds ISO 27001 as UNSATISFIED
    when the notice writes it "ISO/IEC 27001": `_norm` strips the separators, so
    "iso27001" and "isoiec27001" are neither equal nor a substring of each other.
    That is the dangerous direction of error — telling a qualified bidder it does
    not qualify — so a token comparison backs the substring one up.

    A standard's number is its identity, which is what keeps this from being too
    loose: every digit token the requirement names must be held, and at least one
    word must be shared. So ISO/IEC 27001 matches ISO27001, while ISO 9001 (wrong
    number) and KS 27001 (wrong body) both still fail.
    """
    if _string_match(held_name, required_name):
        return True

    held = [token.casefold() for token in _NAME_TOKEN_RE.findall(str(held_name or ""))]
    required = [
        token.casefold() for token in _NAME_TOKEN_RE.findall(str(required_name or ""))
    ]
    if not held or not required:
        return False

    held_digits = {token for token in held if token.isdigit()}
    required_digits = {token for token in required if token.isdigit()}
    if not required_digits or not required_digits <= held_digits:
        return False

    held_words = {token for token in held if not token.isdigit()}
    required_words = {token for token in required if not token.isdigit()}
    return bool(held_words & required_words)


def _performance_candidates(
    profile: CompanyProfileSnapshot,
    requirement: QualificationRequirement,
    reference_date: date,
) -> tuple[list[ProfilePerformanceFact], bool, list[ProfilePerformanceFact]]:
    """기간 안의 실적 후보, 날짜가 모호한 실적 유무, 열린 어휘 때문에 빠진 실적 유무.

    경험분야·발주처는 통제 어휘가 없는 자유 문자열이다(ADR 0001 문제 4). 기간 안의 실적이
    문자열 비교로만 빠졌다면 "다르다"가 아니라 "같은지 모른다"이므로, 호출부는 그 경우
    미달로 확정하지 않고 확인 필요로 돌린다.
    """
    cutoff = (
        _subtract_months(reference_date, requirement.period_months)
        if requirement.period_months is not None
        else None
    )
    client_requirement = str(requirement.scope.get("client_requirement") or "").strip()

    candidates: list[ProfilePerformanceFact] = []
    has_ambiguous_date = False
    vocabulary_unresolved: list[ProfilePerformanceFact] = []
    field = requirement.scope.get("experience_field")
    for item in profile.performances:
        vocabulary_ok = True
        if field and not any(_string_match(value, field) for value in [item.name, *item.fields]):
            vocabulary_ok = False
        if vocabulary_ok and client_requirement:
            client_ok = _string_match(item.client_name or "", client_requirement)
            if not client_ok and _norm(client_requirement) == _norm("공공기관"):
                client_ok = bool(item.client_institution_code) or "공공" in _norm(item.client_name)
            vocabulary_ok = client_ok
        if item.completed_at is not None:
            if item.completed_at > reference_date:
                continue
            if cutoff is not None and item.completed_at < cutoff:
                continue
        elif item.completed_year is not None:
            earliest = date(item.completed_year, 1, 1)
            latest = date(item.completed_year, 12, 31)
            if earliest > reference_date or (cutoff is not None and latest < cutoff):
                continue
            if latest > reference_date or (cutoff is not None and earliest < cutoff):
                has_ambiguous_date = has_ambiguous_date or vocabulary_ok
                continue
        else:
            has_ambiguous_date = has_ambiguous_date or vocabulary_ok
            continue
        if not vocabulary_ok:
            vocabulary_unresolved.append(item)
            continue
        candidates.append(item)
    return candidates, has_ambiguous_date, vocabulary_unresolved


# [재현 2026-09-13] 2026-07-01 광주·전남 행정통합으로 지역 이름에 위계가 생겼다.
# 전남광주통합특별시 안에 "종전 광주광역시" 와 "종전 전라남도" 가 있고, 통합 전 이름
# "광주광역시" · "전라남도" 도 같은 하위 지역을 가리킨다. 부분문자열 비교는 이 관계를
# 모른다 — R26BK01634263 004차수가 소재지를 "전남광주통합특별시" 에서 "종전 광주광역시" 로
# 좁혔을 때, 통합시 단위로 등록된 회사 셋에 전부 '미달' 을 확정했다. 그 회사가 옛 광주
# 안에 있을 수도 있어서 프로필로는 답할 수 없는데 답한 것이다 — 잘못된 확정 미달.
#
# 하위 -> 상위. 키는 _norm 을 거친 형태(공백 없음).
_REGION_PARENT: dict[str, str] = {
    "종전광주광역시": "전남광주통합특별시",
    "종전전라남도": "전남광주통합특별시",
    "광주광역시": "전남광주통합특별시",
    "전라남도": "전남광주통합특별시",
}


# 지역 값은 모델이 쓴 문구가 그대로 들어온다(canonical/legacy_slots.py 의 지역_raw).
# 같은 곳을 "종전 광주광역시", "종전 광주광역시 관내", "광주광역시(종전)" 로 제각기 적는데,
# 표를 정확히 일치로만 찾으면 표기 하나에 위계가 사라지고 다시 미달을 확정한다.
# 통합 전후를 가리키는 꾸밈말만 떼어내고 표를 찾는다. 떼어낸 열쇠는 표 조회에만 쓰고,
# 두 문구가 같은 곳인지 보는 비교(_string_match)는 원래 값으로 한다.
_REGION_PREFIXES = ("종전의", "종전", "옛")
# 괄호는 _norm 이 지우므로 "광주광역시(종전)" 은 "광주광역시종전" 으로 들어온다.
_REGION_SUFFIXES = ("소재지", "소재", "관내", "일원", "전역", "지역", "종전의", "종전", "옛")
# "구"를 범용 prefix로 떼면 구미시·구리시·구례군 같은 실제 지명이 훼손된다.
# 확인된 과거 명칭 표현만 명시적으로 alias 처리한다.
_REGION_ALIASES = {
    "구광주광역시": "광주광역시",
}


def _region_key(value: object) -> str:
    """표를 찾기 위한 열쇠. 꾸밈말을 다 뗄 때까지 반복한다("종전 광주광역시 일원")."""
    key = _norm(value)
    changed = True
    while changed:
        changed = False
        for prefix in _REGION_PREFIXES:
            if key.startswith(prefix) and len(key) > len(prefix):
                key, changed = key[len(prefix):], True
        for suffix in _REGION_SUFFIXES:
            if key.endswith(suffix) and len(key) > len(suffix):
                key, changed = key[: -len(suffix)], True
    return _REGION_ALIASES.get(key, key)


def _region_relation(observed: str, required: object) -> str:
    """'match' | 'contained' | 'too_coarse' | 'none'.

    contained  프로필이 하위 지역이고 요건이 그 상위 — 포함되므로 충족.
    too_coarse 요건이 하위 지역인데 프로필은 상위 단위 — 프로필로는 가를 수 없다.
    """
    obs, req = _norm(observed), _norm(required)
    if not obs or not req:
        return "none"
    # 양쪽에 사전에 있는 지역 이름이 있으면 이름끼리 맞춘다 — 같은 시·군·구인가, 같은(또는 통합된) 시·도인가.
    # 문자열 포함으로 맞추면 "충청남도" 회사가 "충청남도 보령시" 요건에 맞고, "의북구" 같은 값이 누구와도 안 맞는다.
    by_name = region_name_relation(str(observed), str(required))
    if by_name is not None:
        return by_name
    obs_key, req_key = _region_key(observed), _region_key(required)
    if obs_key and obs_key == req_key:
        # 꾸밈말만 다른 같은 지역. "종전 광주광역시" 와 "광주광역시(종전)".
        return "match"
    if obs_key and len(req_key) > len(obs_key) and req_key.startswith(obs_key):
        # 프로필이 요건보다 넓다 — "충청남도" 로만 등록된 회사로는 "충청남도 보령시" 안인지 알 수 없다.
        # 문자열 포함으로 맞다고 하면 자격 없는 회사에 '충족' 이 나간다(2026-10-06 표본).
        return "too_coarse"
    if _string_match(observed, required):
        return "match"
    if _REGION_PARENT.get(obs_key) == req_key:
        return "contained"
    if _REGION_PARENT.get(req_key) == obs_key:
        return "too_coarse"
    return "none"


def _judge_region(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    observed = profile.region_name or profile.region_code
    if not observed or observed == "NONE":
        return _unknown(requirement, preflight_case_id)
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    relation = _region_relation(observed, requirement.value)
    if relation == "too_coarse":
        # 통합시 단위 프로필로는 종전 시·도 안인지 알 수 없다. 미달로 확정하면 옛 광주
        # 안에 있는 회사를 떨어뜨린다. 상세 주소를 물어야 하므로 확인 필요로 넘긴다.
        return _unknown(requirement, preflight_case_id)
    matched = relation in {"match", "contained"}
    if not matched and not profile.completeness.region:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if matched else "UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MATCH" if matched else "RULE_MISMATCH",
        profile_refs=[_profile_ref("company", "region", observed)],
    )


_SIZE_WORDS_RE = re.compile(r"중견기업|대기업|중소기업|중기업|소기업|소상공인")
_SIZE_FILLER_RE = re.compile(r"[\s,，·ㆍ/]|및|와|과|또는|이나|자")


def _company_size_set(value: str) -> set[str] | None:
    """규모 낱말과 이음말로만 된 값이면 허용 규모의 합집합. 다른 글자가 섞이면 None.

    "대기업 및 중견기업" 은 별칭표에 없지만 닫힌 낱말 둘의 합집합이다. 문자열 비교로 떨어지면
    배제(EXCLUDE) 요건에서 중견기업 회사가 충족으로 나온다.
    """
    words = _SIZE_WORDS_RE.findall(value)
    if not words or _SIZE_FILLER_RE.sub("", _SIZE_WORDS_RE.sub("", value)):
        return None
    allowed: set[str] = set()
    for word in words:
        allowed |= _COMPANY_SIZE_ALIASES[word]
    return allowed


def _judge_company_size(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    observed = profile.company_size
    if not observed or observed == "NONE":
        return _unknown(requirement, preflight_case_id)
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)

    expected_text = str(requirement.value).strip()
    allowed = _COMPANY_SIZE_ALIASES.get(expected_text) or _company_size_set(expected_text)
    matched = observed in allowed if allowed is not None else _string_match(observed, expected_text)

    # "대기업 및 중견기업 참여 제한" names the sizes barred from bidding, so being
    # one of them is what fails. Extraction records that in `scope`.
    if str(requirement.scope.get("restriction") or "") == "EXCLUDE":
        satisfied = not matched
    else:
        satisfied = matched

    # A combined restriction can also bar members of a large-business group.
    # That is independent of legal company size, so a smaller company remains
    # UNKNOWN until the notice-specific answer is supplied.
    from bidengine.extensions import required_for

    needs_affiliation = any(
        spec.key == "conglomerate_affiliate" for spec in required_for([requirement])
    )
    affiliation = profile.extensions.get("conglomerate_affiliate")
    is_affiliate = (
        affiliation.get("is_affiliate") if isinstance(affiliation, dict) else None
    )
    if satisfied and needs_affiliation:
        if is_affiliate is None:
            return _unknown(requirement, preflight_case_id)
        satisfied = not is_affiliate

    if not satisfied and not profile.completeness.company_size:
        return _unknown(requirement, preflight_case_id)
    if not satisfied and allowed is None:
        # 별칭표에 없는 규모 표현("벤처기업" 등)은 자유 문자열이라 미달을 확정하지 않는다.
        return _vocabulary_unknown(requirement, preflight_case_id, [("company", "company_size", observed)])
    refs = [_profile_ref("company", "company_size", observed)]
    if needs_affiliation and is_affiliate is not None:
        refs.append(_profile_ref("extension", "conglomerate_affiliate", is_affiliate))
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if satisfied else "UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MATCH" if satisfied else "RULE_MISMATCH",
        profile_refs=refs,
    )


_INDUSTRY_CODE_VALUE_RE = re.compile(r"[0-9]{4}")


def _judge_industry(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)

    match = next(
        (
            item
            for item in profile.industries
            if _norm(item.name) == _norm(requirement.value)
            or _norm(item.code) == _norm(requirement.value)
        ),
        None,
    )
    if match is not None:
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED",
            basis_type="PROFILE",
            evidence_held=match.verified,
            reason_code="RULE_MATCH",
            profile_refs=[
                _profile_ref("industry", "code", match.code),
                _profile_ref("industry", "name", match.name),
            ],
        )
    if not profile.completeness.industries:
        return _unknown(requirement, preflight_case_id)
    if not _INDUSTRY_CODE_VALUE_RE.fullmatch(str(requirement.value).strip()):
        # 값이 업종코드가 아니라 이름이다("위생관리용역업(건물청소용역업)"). 이름은 표기가 갈려서
        # ("건물위생관리업", "철근ㆍ콘크리트공사업") 글자가 안 맞는다고 그 업종이 없다고 할 수 없다. 미달로
        # 확정하면 자격 있는 회사가 부적합이 된다(2026-10-06 가상 회사 시험의 틀린 미달 대부분).
        return _vocabulary_unknown(
            requirement, preflight_case_id, [("industry", "name", item.name) for item in profile.industries]
        )
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MISMATCH",
        profile_refs=[],
    )


def _judge_staff(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
) -> Judgment:
    staff = profile.staff
    if staff is None:
        return _unknown(requirement, preflight_case_id)

    role = str(requirement.scope.get("role") or "").strip()
    if role:
        matched_role = next(
            (item for item in staff.roles if _string_match(item.role_name, role)),
            None,
        )
        if matched_role is None:
            if not profile.completeness.staff_roles:
                return _unknown(requirement, preflight_case_id)
            # 역할 이름은 자유 문자열이다. 회사의 역할 목록이 비어 있어도 그 역할이 없다고 확정하지 않는다 — 모델이
            # "입찰대리인은 입찰참가 업체에 재직중인 임·직원이어야" 같은 문장에서 역할을 뽑아 자격 있는 회사가
            # 부적합이 됐다(2026-10-06 무작위 표본). 등록·인증 이름(6b21430)과 같은 원칙.
            return _vocabulary_unknown(
                requirement, preflight_case_id,
                [("staff_role", "role_name", item.role_name) for item in staff.roles],
            )
        if requirement.operator == "MATCH" and requirement.value is not None:
            matched = _string_match(matched_role.role_name, requirement.value)
            if not matched and profile.completeness.staff_roles:
                return _vocabulary_unknown(
                    requirement, preflight_case_id, [("staff_role", "role_name", matched_role.role_name)]
                )
        else:
            compared = _compare_number(
                matched_role.headcount, requirement.operator, requirement.value
            )
            if compared is None:
                return _unknown(requirement, preflight_case_id, unsupported=True)
            matched = compared
        if not matched and not profile.completeness.staff_roles:
            return _unknown(requirement, preflight_case_id)
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED" if matched else "UNSATISFIED",
            basis_type="PROFILE",
            evidence_held=matched_role.verified,
            reason_code="RULE_MATCH" if matched else "RULE_MISMATCH",
            profile_refs=[
                _profile_ref("staff_role", "role_name", matched_role.role_name),
                _profile_ref("staff_role", "headcount", matched_role.headcount),
            ],
        )

    compared = _compare_number(staff.total_count, requirement.operator, requirement.value)
    if compared is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if not compared and not profile.completeness.staff_total:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if compared else "UNSATISFIED",
        basis_type="PROFILE",
        evidence_held=staff.verified,
        reason_code="RULE_MATCH" if compared else "RULE_MISMATCH",
        profile_refs=[_profile_ref("staff", "total_count", staff.total_count)],
    )


def _judge_performance_amount(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    candidates, has_ambiguous_date, vocabulary_unresolved = _performance_candidates(
        profile, requirement, reference_date
    )
    if not candidates:
        if vocabulary_unresolved:
            return _vocabulary_unknown(requirement, preflight_case_id, [("performance", "name", item.name) for item in vocabulary_unresolved])
        if has_ambiguous_date or not profile.completeness.performances:
            return _unknown(requirement, preflight_case_id)
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="UNSATISFIED",
            basis_type="PROFILE",
            reason_code="RULE_MISMATCH",
        )

    aggregation = str(requirement.scope.get("aggregation") or "UNSPECIFIED").upper()
    if aggregation == "SUM":
        observed = float(sum(item.amount for item in candidates))
        contributing = candidates
    else:
        best = max(candidates, key=lambda item: item.amount)
        observed = float(best.amount)
        contributing = [best]

    compared = (
        _compare_range(observed, requirement.scope)
        if requirement.operator == "RANGE"
        else _compare_number(observed, requirement.operator, requirement.value)
    )
    if compared is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if not compared and vocabulary_unresolved:
        return _vocabulary_unknown(requirement, preflight_case_id, [("performance", "name", item.name) for item in vocabulary_unresolved])
    if not compared and has_ambiguous_date:
        return _unknown(requirement, preflight_case_id)
    if aggregation == "UNSPECIFIED" and len(candidates) > 1:
        summed = sum(item.amount for item in candidates)
        sum_compared = _compare_range(summed, requirement.scope) if requirement.operator == "RANGE" else _compare_number(summed, requirement.operator, requirement.value)
        if sum_compared != compared:
            return _unknown(requirement, preflight_case_id, unsupported=True)
    if not compared and not profile.completeness.performances:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if compared else "UNSATISFIED",
        basis_type="PROFILE",
        evidence_held=all(item.verified for item in contributing),
        reason_code="RULE_MATCH" if compared else "RULE_MISMATCH",
        profile_refs=[
            _profile_ref("performance", "ref", item.ref) for item in contributing
        ]
        + [_profile_ref("performance", "observed_amount", int(observed))],
    )


def _judge_performance_count(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    candidates, has_ambiguous_date, vocabulary_unresolved = _performance_candidates(
        profile, requirement, reference_date
    )
    observed = len(candidates)
    compared = _compare_number(observed, requirement.operator, requirement.value)
    if compared is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if not compared and vocabulary_unresolved:
        return _vocabulary_unknown(requirement, preflight_case_id, [("performance", "name", item.name) for item in vocabulary_unresolved])
    if not compared and has_ambiguous_date:
        return _unknown(requirement, preflight_case_id)
    if not compared and not profile.completeness.performances:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="SATISFIED" if compared else "UNSATISFIED",
        basis_type="PROFILE",
        evidence_held=bool(candidates) and all(item.verified for item in candidates),
        reason_code="RULE_MATCH" if compared else "RULE_MISMATCH",
        profile_refs=[
            _profile_ref("performance", "ref", item.ref) for item in candidates
        ]
        + [_profile_ref("performance", "observed_count", observed)],
    )


def _judge_experience_field(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)
    candidates, has_ambiguous_date, vocabulary_unresolved = _performance_candidates(
        profile, requirement, reference_date
    )
    matched = next(
        (
            item
            for item in candidates
            if any(_string_match(field, requirement.value) for field in item.fields)
            or _string_match(item.name, requirement.value)
        ),
        None,
    )
    if matched is not None:
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED",
            basis_type="PROFILE",
            evidence_held=matched.verified,
            reason_code="RULE_MATCH",
            profile_refs=[_profile_ref("performance", "ref", matched.ref)],
        )
    # 기간 안의 실적은 있는데 분야 이름이 문자열로 안 맞았다면 같은 분야인지 모르는 것이다.
    if vocabulary_unresolved or candidates:
        return _vocabulary_unknown(
            requirement, preflight_case_id, [("performance", "name", item.name) for item in [*candidates, *vocabulary_unresolved]]
        )
    if has_ambiguous_date:
        return _unknown(requirement, preflight_case_id)
    if not profile.completeness.performances:
        return _unknown(requirement, preflight_case_id)
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MISMATCH",
    )


def _judge_certification(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    if requirement.operator not in {"MATCH", "="} or requirement.value is None:
        return _unknown(requirement, preflight_case_id, unsupported=True)

    issuer_requirement = str(requirement.scope.get("issuer") or "").strip()
    name_matches = [
        item
        for item in profile.certifications
        if _certification_match(item.name, requirement.value)
        or _certification_match(item.certification_code or "", requirement.value)
    ]
    valid_matches = [
        item
        for item in name_matches
        if (not issuer_requirement or _string_match(item.issuer_name or "", issuer_requirement))
        and (item.expires_at is None or item.expires_at >= reference_date)
        and (item.issued_at is None or item.issued_at <= reference_date)
    ]
    # 등록·면허 이름은 회사가 업종으로 등록해 둔 경우가 많다("건축공사업"). 인증 목록만 보면
    # 업종으로 가진 회사를 놓친다 — 등록 종류면 업종 이름도 본다.
    registration_kind = str(requirement.scope.get("kind") or "") in {"REGISTRATION", "LICENSE"}
    industry_match = (
        next((item for item in profile.industries if _string_match(item.name, requirement.value)), None)
        if registration_kind and not valid_matches
        else None
    )
    if industry_match is not None:
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED",
            basis_type="PROFILE",
            evidence_held=industry_match.verified,
            reason_code="RULE_MATCH",
            profile_refs=[
                _profile_ref("industry", "code", industry_match.code),
                _profile_ref("industry", "name", industry_match.name),
            ],
        )

    if valid_matches:
        item = valid_matches[0]
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED",
            basis_type="PROFILE",
            evidence_held=item.verified,
            reason_code="RULE_MATCH",
            profile_refs=[
                _profile_ref("certification", "ref", item.ref),
                _profile_ref("certification", "name", item.name),
                *(
                    [_profile_ref("certification", "certification_code", item.certification_code)]
                    if item.certification_code
                    else []
                ),
            ],
        )

    if not profile.completeness.certifications:
        return _unknown(requirement, preflight_case_id)

    # 이름은 맞는데 발급기관 이름만 안 맞은 경우, 또는 이름으로 요구했는데 회사가 다른 이름의
    # 인증을 가진 경우는 자유 문자열 불일치다. 코드로 요구했거나(숫자) 유효기간이 지난 것은
    # 닫힌 비교라 그대로 미달이다.
    issuer_only = [
        item for item in name_matches
        if issuer_requirement and not _string_match(item.issuer_name or "", issuer_requirement)
        and (item.expires_at is None or item.expires_at >= reference_date)
        and (item.issued_at is None or item.issued_at <= reference_date)
    ]
    if issuer_only:
        return _vocabulary_unknown(
            requirement, preflight_case_id, [("certification", "issuer_name", item.issuer_name or "") for item in issuer_only]
        )
    required_is_code = bool(re.fullmatch(r"[0-9A-Za-z\-]{2,}", str(requirement.value).strip())) and any(
        ch.isdigit() for ch in str(requirement.value)
    ) and not re.search(r"[가-힣]", str(requirement.value))
    held = [
        item for item in profile.certifications
        if (item.expires_at is None or item.expires_at >= reference_date)
        and (item.issued_at is None or item.issued_at <= reference_date)
    ]
    held_industries = profile.industries if registration_kind else []
    # 이름으로 요구한 것은 회사가 등록·인증을 하나도 갖지 않았어도 미달로 확정하지 않는다. 모델이 서술형 조항에서
    # 뽑은 이름("제조", "공급관련입찰참가자격", "이에준하")은 표기도 뜻도 열려 있어, 목록에 없다고 그 자격이
    # 없다고 할 수 없다(2026-10-06 다섯 번째 표본: 자격 있는 회사가 이 경로로 3개 공고에서 부적합).
    # 번호(품명번호 등)로 요구한 것은 닫힌 비교라 그대로 미달이다.
    if not name_matches and not required_is_code:
        return _vocabulary_unknown(
            requirement, preflight_case_id,
            [("certification", "name", item.name) for item in held]
            + [("industry", "name", item.name) for item in held_industries],
        )

    refs = [
        _profile_ref("certification", "ref", item.ref)
        for item in name_matches
    ]
    return _judgment(
        requirement=requirement,
        preflight_case_id=preflight_case_id,
        status="UNSATISFIED",
        basis_type="PROFILE",
        reason_code="RULE_MISMATCH",
        profile_refs=refs,
    )


def judge_requirement(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    *,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    # 안전 가드가 가장 먼저다. 판정하기 위험한 조항(복합 조건·부정 조건 등)이면
    # 확장 경로라고 예외일 이유가 없다. 순서를 뒤집으면 SW등급 요건이 가드를
    # 우회해서, 하나로 줄일 수 없는 조건을 충족/미충족으로 단정하게 된다.
    #
    # [2026-09-15] 추출이 가드 평가를 마치고 구조에 새긴 요건(scope.guard == "assessed")은
    # raw 를 다시 읽지 않는다 — condition_complexity 가 그 결과다. 추출이 ANY_OF 로 담아 둔
    # 대안 묶음의 raw 에는 '또는' 이 있고, 그것을 여기서 또 읽으면 이미 구조로 표현된 대안을
    # 다시 막는다(J14: 1257 보유 회사가 적합이 아니라 확인 필요). 표시가 없는 요건(예전 저장
    # 행, 골든 고정본)은 예전처럼 raw 를 본다.
    #
    # 예외 단서가 붙은 코드(scope.guard_reason == EXCEPTION_UNRESOLVED)는 "코드 OR 예외 사실"
    # 이다(골든 J13~J16 transport). 코드를 실제로 가진 회사는 예외를 따질 것 없이 충족이고,
    # 없는 회사만 예외 사실이 확인될 때까지 확인 필요다 — 미달로 확정하지 않는다. 그래서
    # 이 원자는 보통 경로로 판정한 뒤 SATISFIED 가 아니면 UNKNOWN 으로 바꾼다.
    exception_alternative = (
        is_guard_assessed(requirement.scope)
        and requirement.scope.get("guard_reason") == GUARD_REASON_EXCEPTION
    )
    if (requirement.condition_complexity == "composite" and not exception_alternative) or (
        not is_guard_assessed(requirement.scope) and unsafe_clause_reason(requirement.raw)
    ):
        return _unknown(requirement, preflight_case_id, unsupported=True)
    if exception_alternative:
        base = _judge_by_type(requirement, profile, preflight_case_id, reference_date)
        return base if base.status == "SATISFIED" else _unknown(requirement, preflight_case_id)
    return _judge_by_type(requirement, profile, preflight_case_id, reference_date)


def _judge_by_type(
    requirement: QualificationRequirement,
    profile: CompanyProfileSnapshot,
    preflight_case_id: str,
    reference_date: date,
) -> Judgment:
    # 공고별 확장 요건은 일반 유형보다 먼저 판정한다. 특히 SW기술자 등급은
    # `_judge_staff` 로도 흘러가면 안 된다 — 같은 요건을 두 번 판정하게 되고,
    # 역할 이름 매칭이라는 더 약한 기준이 결과를 뒤집을 수 있다.
    from bidengine.extensions import spec_for_requirement

    extension = spec_for_requirement(requirement)
    if extension is not None:
        status, _detail = extension.judge(
            profile.extensions.get(extension.key), requirement
        )
        if status is None:
            return _unknown(requirement, preflight_case_id)
        satisfied = status == "충족"
        return _judgment(
            requirement=requirement,
            preflight_case_id=preflight_case_id,
            status="SATISFIED" if satisfied else "UNSATISFIED",
            basis_type="USER_ANSWER",
            reason_code="RULE_MATCH" if satisfied else "RULE_MISMATCH",
            profile_refs=[
                _profile_ref(
                    "extension", extension.key, profile.extensions.get(extension.key)
                )
            ],
        )

    if requirement.type == "REGION":
        return _judge_region(requirement, profile, preflight_case_id)
    if requirement.type == "COMPANY_SIZE":
        return _judge_company_size(requirement, profile, preflight_case_id)
    if requirement.type == "INDUSTRY":
        return _judge_industry(requirement, profile, preflight_case_id)
    if requirement.type == "STAFF":
        return _judge_staff(requirement, profile, preflight_case_id)
    if requirement.type == "PERFORMANCE_AMOUNT":
        return _judge_performance_amount(
            requirement, profile, preflight_case_id, reference_date
        )
    if requirement.type == "PERFORMANCE_COUNT":
        return _judge_performance_count(
            requirement, profile, preflight_case_id, reference_date
        )
    if requirement.type == "EXPERIENCE_FIELD":
        return _judge_experience_field(
            requirement, profile, preflight_case_id, reference_date
        )
    if requirement.type == "REGISTRATION_CERTIFICATION":
        return _judge_certification(
            requirement, profile, preflight_case_id, reference_date
        )
    return _unknown(requirement, preflight_case_id, unsupported=True)


def derive_overall_status(
    requirements: list[QualificationRequirement],
    judgments: list[Judgment],
    *,
    analysis_status: str = "SUCCEEDED",
    coverage_complete: bool | None = None,
) -> OverallQualificationStatus:
    """적합은 (1) 필수 요건이 모두 충족이고 (2) 공고의 참가자격을 다 봤을 때만 준다.

    (2)는 커버리지가 있으면 커버리지로, 없으면(예전 분석) 분석 상태로 판단한다. 분석 상태
    PARTIAL 은 "후보 하나가 검증에서 떨어졌다" 같은 파이프라인 사정을 섞어 쓰므로, 커버리지가
    있으면 그쪽이 우선이다. 부적합은 (2)와 무관하다 — 본 요건 중 하나가 확정 미달이면 된다.
    """
    seen_everything = coverage_complete if coverage_complete is not None else analysis_status == "SUCCEEDED"
    status_by_key = {item.requirement_key: item.status for item in judgments}
    grouped: dict[str, tuple[str, list[str]]] = {}

    for requirement in requirements:
        if requirement.requirement_role != "mandatory":
            continue
        group_key = requirement.requirement_group_key or requirement.requirement_key
        operator = requirement.group_operator or "ALL_OF"
        current_operator, statuses = grouped.setdefault(group_key, (operator, []))
        if current_operator != operator:
            statuses.append("UNKNOWN")
        statuses.append(status_by_key.get(requirement.requirement_key, "UNKNOWN"))

    group_statuses: list[str] = []
    for operator, statuses in grouped.values():
        if operator == "ANY_OF":
            if "SATISFIED" in statuses:
                group_statuses.append("SATISFIED")
            elif "UNKNOWN" in statuses:
                group_statuses.append("UNKNOWN")
            else:
                group_statuses.append("UNSATISFIED")
        else:
            if "UNSATISFIED" in statuses:
                group_statuses.append("UNSATISFIED")
            elif "UNKNOWN" in statuses:
                group_statuses.append("UNKNOWN")
            else:
                group_statuses.append("SATISFIED")

    if "UNSATISFIED" in group_statuses:
        return "ineligible"
    if "UNKNOWN" in group_statuses or not group_statuses or not seen_everything:
        return "insufficient_data"
    return "eligible"


def judge_requirements(
    requirements: list[QualificationRequirement],
    profile: CompanyProfileSnapshot,
    *,
    preflight_case_id: str,
    reference_date: date,
    analysis_status: str = "SUCCEEDED",
    coverage_complete: bool | None = None,
) -> JudgmentEvaluation:
    judgments = [
        judge_requirement(
            requirement,
            profile,
            preflight_case_id=preflight_case_id,
            reference_date=reference_date,
        )
        for requirement in requirements
    ]
    return JudgmentEvaluation(
        judgments=judgments,
        overall_status=derive_overall_status(
            requirements, judgments, analysis_status=analysis_status, coverage_complete=coverage_complete
        ),
    )
