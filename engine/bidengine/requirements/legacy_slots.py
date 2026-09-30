"""Adapter from source-grounded extraction slots to canonical requirements.

The extraction layer keeps human-readable Korean slot types as an internal
interface. Production maps those slots into the closed eight-type canonical
taxonomy. Unsupported or incomplete slots become diagnostics rather than being
forced into a judgment-ready requirement.
"""

from __future__ import annotations

import re
from typing import Any

from bidengine.contracts import QualificationRequirement, RequirementOperator, RequirementType
from bidengine.judgment.clause_safety import GUARD_ASSESSED, assess_clause, strip_decorations, unsafe_clause_reason
from bidengine.judgment.rules import _COMPANY_SIZE_ALIASES
from bidengine.requirements.deduplicate import _INDUSTRY_NAME_VALUE_RE, _REGISTRATION_ACT_VALUE_RE

_MIN_PLAUSIBLE_AMOUNT_KRW = 10_000
_COUNT_RE = re.compile(r"(\d+)\s*(?:건|회)\s*(이상|초과|이하|미만)?")
_INDUSTRY_CODE_RE = re.compile(r"업종\s*코드\s*[:：]?\s*([0-9]{4}(?:\s*[,/·]\s*[0-9]{4})*)(?![0-9])")
# 지역값 뒤에 붙는 서술 꼬리 — "전남광주통합특별시에 소재한 업체" → "전남광주통합특별시".
_REGION_TAIL_RE = re.compile(
    r"(?:에|의|을|를)?\s*(?:소재한?|위치한?|있는|둔|두고\s*있는)\s*(?:업체|자|기업|법인|사업자)?\s*$"
)
_SIZE_EXCLUSION_RE = re.compile(
    r"참여\s*(?:제한|불가|배제|금지)"
    r"|참가\s*(?:제한|불가|배제)"
    r"|참여할\s*수\s*없"
    r"|참여\s*(?:를)?\s*(?:제외|배제)"
    r"|입찰\s*참가\s*자격\s*(?:을)?\s*제한"
)


# 닫힌 식별자 — 사람이 달리 쓸 수 없는 값. 업종코드 4자리, 세부품명번호 10자리.
# 모델이 유형을 뭐라고 붙이든 이 숫자는 원문에 그대로 있다.
_PRODUCT_CODE_RE = re.compile(r"(?<![0-9])([0-9]{10})(?![0-9])")
_REGISTRATION_CONTEXT_RE = re.compile(r"등록|신고|영업|허가|면허")
_PRODUCT_CONTEXT_RE = re.compile(r"직접\s*생산\s*확인|세부\s*품명|품명\s*번호")


def _compact(text: str) -> str:
    """닫힌 식별자를 읽을 때 쓰는 본문 — 공백·줄바꿈을 전부 걷어낸다.

    [재현 2026-09-15, 골든 01688607] PDF 원문이 "[업⏎종코드: 5898]" 처럼 **낱말 안에서** 줄을
    바꾼다. 모델 raw 는 원문 구간으로 스냅되므로 그 줄바꿈이 그대로 들어오고, "업종코드"
    정규식이 못 읽어 코드 5898 대신 이름 값으로 떨어졌다. 숫자는 사람이 달리 못 쓰는 값이라
    공백을 걷어내도 뜻이 안 바뀐다.
    """
    return re.sub(r"\s+", "", text or "")


# 회사 규모 낱말도 닫힌 어휘다 — 소상공인·소기업·중소기업·중견기업·대기업 다섯 개뿐이고,
# 판정기는 이 다섯 낱말을 열쇠로 허용 규모 집합을 찾는다(`_COMPANY_SIZE_ALIASES`).
#
# [재현 2026-09-15, 골든 17개 실측] 그런데 모델은 "중·소기업·소상공인", "중소기업자 및
# 소상공인" 처럼 낱말을 이어 붙여 낸다. 그 값은 alias 표에 없어서 판정기가 문자열 비교로
# 떨어지고, SMALL 회사가 **UNSATISFIED** 를 받았다(실제 실행으로 확인). 같은 사실이
# 실행마다 COMPANY_SIZE / "…확인서" REGISTRATION_CERTIFICATION / 검증 탈락 세 모양으로 갈려
# 7개 공고가 흔들렸다. 골든셋은 전부 COMPANY_SIZE(allowed 집합)로 본다.
#
# 이어 붙인 값은 각 낱말의 허용 집합의 합집합이다 — "소기업·소상공인" = 소기업(MICRO,SMALL)
# ∪ 소상공인(MICRO) = 소기업. 합집합이 정확히 어느 한 낱말의 집합과 같을 때만 그 낱말로
# 정규화한다. "대기업 및 중견기업" 처럼 어느 낱말과도 안 맞으면 손대지 않는다(그건 참여
# 제한 조항이고 기존 EXCLUDE 경로가 맞게 처리한다). 법령명 안의 낱말("「중소기업기본법」에
# 따른 소상공인")이 섞이지 않게 먼저 인용을 벗긴다.
_SIZE_WORD_RE = re.compile(r"중견기업|대기업|중소기업|소기업|소상공인")
# "중·소기업" 은 중기업·소기업을 가운뎃점으로 이어 쓴 것이다 — 점을 걷어내면 "중소기업" 이다.
_SIZE_JOINERS_RE = re.compile(r"[·ㆍ.\s]")
# 규모 확인서 이름 — 낱말·'자'·및/와/과·확인서/증명서 접미만으로 이루어진 값(점·공백은 미리
# 걷어낸다). "ISO 9001" 처럼 고유명사가 섞이면 진짜 인증이므로 여기 안 걸린다.
_SIZE_CERT_NAME_RE = re.compile(
    r"^(?:(?:중견기업|대기업|중소기업|소기업|소상공인)자?[,및와과]*)+(?:확인서|증명서|확인증)?$"
)


def _size_text(text: str) -> str:
    return _SIZE_JOINERS_RE.sub("", strip_decorations(text or ""))


def company_size_alias(text: str) -> str | None:
    """규모 낱말들의 허용 집합 합집합이 정확히 한 낱말의 집합이면 그 낱말. 아니면 None."""
    allowed: set[str] = set()
    for word in _SIZE_WORD_RE.findall(_size_text(text)):
        allowed |= _COMPANY_SIZE_ALIASES[word]
    if not allowed:
        return None
    return next((key for key, sizes in _COMPANY_SIZE_ALIASES.items() if sizes == allowed), None)


def is_company_size_certificate_name(name: str) -> bool:
    return bool(_SIZE_CERT_NAME_RE.fullmatch(_size_text(name)))


# "A(1257) 또는 B(6770) 또는 C(6786) 등록업체" — 안전 가드는 이것을 막는다. 하나로
# 줄일 수 없는 조건을 충족/미충족으로 단정하면 안 되기 때문이다. 옳은 판단이지만,
# **ANY_OF 가 바로 그 '또는' 의 안전한 표현**이다. 줄이지 않고 관계를 그대로 담을 수
# 있으면 막을 이유가 없다. 그래서 이 모양 하나만 좁게 연다.
#
# 조건을 좁게 두는 이유는 '또는' 이 늘 대등한 선택지는 아니기 때문이다 — "A 또는
# B 기준을 충족한 업체" 처럼 뒤쪽이 예외·완화 조항이면 ANY_OF 가 아니다. 그래서
# 갈라진 조각이 **전부 업종명(업종코드) 하나씩** 일 때만 인정한다.
_ALTERNATION_SPLIT_RE = re.compile(r"\s*또는\s*")
_EXCEPTION_WORDS_RE = re.compile(
    r"다만|단서|예외|제외|불구하고|각\s*호|아니(?:어야|하여야|한)|해당되지|경우에\s*한"
)
# "기타자유업(행사대행업)(9901)" 처럼 업종명 뒤에 설명 괄호가 하나 더 끼기도 한다(01684825, J20).
_NAMED_INDUSTRY_CODE_RE = re.compile(r"[가-힣A-Za-z·ㆍ\s]{2,}?업\s*\)?\s*\(\s*([0-9]{4})\s*\)")
# [재현 2026-09-15, 검수] "가공업(1257)을 등록하고 ISO 9001을 보유한 업체 또는 운반업(1227)을
# 등록한 업체" 를 실제로 돌리면 ["1257","1227"] 를 돌려줬다. 조각마다 코드가 "하나 있는지"만
# 보고 "그것 말고 다른 게 있는지"는 안 봤다 — "AND ISO 9001" 이 조용히 사라진 채
# (1257 AND ISO 9001) OR 1227 이 1257 OR 1227 로 줄었다. 코드 문구를 걷어낸 나머지에 이런
# 낱말이 남으면 코드 하나로 안 줄어드는 추가 조건이 있다는 뜻이라 ANY_OF 를 접지 않는다.
_EXTRA_CONDITION_RE = re.compile(
    r"보유|겸비|겸한|충족|이상|미만|이내|해당|자격증|인증서?|증명서|면허증"
    r"|ISO\s*[0-9]|KS\s*[A-Za-z0-9]|동시에|함께|모두|각각"
)


def industry_code_alternation(raw: str) -> list[str] | None:
    """'또는' 으로 갈린 조각이 전부 업종명(코드) 하나씩이면 그 코드 목록. 아니면 None."""
    if _EXCEPTION_WORDS_RE.search(raw):
        return None
    parts = _ALTERNATION_SPLIT_RE.split(raw)
    if len(parts) < 2:
        return None
    codes: list[str] = []
    for part in parts:
        found = _NAMED_INDUSTRY_CODE_RE.findall(_compact(part))
        if len(found) != 1:
            return None
        # 코드 문구를 뺀 나머지에 "보유·충족·ISO…" 같은 낱말이 남으면, 이 조각은 코드
        # 하나로 안 줄어드는 다른 조건과 AND 로 묶여 있다는 뜻이다. 그 조건은 우리가 못
        # 줄이므로 전체를 ANY_OF 로 열지 않는다 — 위 가드가 UNMAPPED 로 안전하게 받는다.
        remainder = _NAMED_INDUSTRY_CODE_RE.sub("", part, count=1)
        if _EXTRA_CONDITION_RE.search(remainder):
            return None
        codes.append(found[0])
    if len(set(codes)) != len(codes):
        return None
    return codes


def salvage_closed_identifier(raw: str) -> tuple[RequirementType, str] | None:
    """분류가 '기타요건' 으로 와도 원문의 닫힌 식별자로 유형을 되살린다.

    되살리는 기준을 좁게 둔다 — 식별자가 **정확히 하나**이고, 그것이 등록·신고 맥락에
    쓰였을 때만. 여러 개면 AND/OR 관계를 모르므로 살리지 않는다(이미 업종요건 경로가
    같은 이유로 멈춘다). 숫자가 아닌 표현은 건드리지 않는다 — 지역명·인증명처럼 사람이
    달리 쓸 수 있는 값을 여기서 추측하기 시작하면 틀린 확정으로 간다.
    """
    industry_codes = {
        code
        for group in _INDUSTRY_CODE_RE.findall(_compact(raw))
        for code in re.findall(r"[0-9]{4}", group)
    }
    if len(industry_codes) == 1 and _REGISTRATION_CONTEXT_RE.search(raw):
        return "INDUSTRY", next(iter(industry_codes))

    product_codes = set(_PRODUCT_CODE_RE.findall(_compact(raw)))
    if len(product_codes) == 1 and _PRODUCT_CONTEXT_RE.search(raw):
        return "REGISTRATION_CERTIFICATION", next(iter(product_codes))

    return None


def _squash_name(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _op(word: str | None) -> RequirementOperator | None:
    return {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}.get(word)  # type: ignore[return-value]


def _performance_scope(slot: dict[str, Any], *, aggregation: str | None = None) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    if aggregation is not None:
        scope["aggregation"] = aggregation
    client_requirement = (slot.get("실적기관_raw") or "").strip()
    if client_requirement:
        scope["client_requirement"] = client_requirement
    experience_field = (slot.get("경험분야_raw") or "").strip()
    if experience_field:
        scope["experience_field"] = experience_field
    return scope


def adapt_legacy_slot(
    slot: dict[str, Any],
    *,
    notice_version_id: str,
    key_prefix: str,
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """Map one validated extraction slot into zero or more canonical requirements."""
    slot_type = slot.get("유형")
    raw = (slot.get("raw") or "").strip()
    # [재현 2026-09-15, 검수 2차] 나라장터 절차 가드가 raw 만 보면 놓치는 경우가 있었다 —
    # 01634263-003 를 5회 중 1회는 모델이 "「국가종합전자조달시스템 입찰참가자격등록규정」"
    # 을 raw 가 아니라 등록인증_raw 에 담고, raw 에는 "입찰참가등록 마감일시까지 …" 꼬리만
    # 남겼다. 어느 필드에 담겼는지는 모델 마음이라 가드는 둘을 합쳐서 본다. 요건에 실제로
    # 저장되는 raw 는 그대로(raw=raw) — 가드 판단에만 쓴다.
    registration_name = (slot.get("등록인증_raw") or "").strip()
    unsafe_reason = unsafe_clause_reason(f"{raw} {registration_name}" if registration_name else raw)
    alternation = (
        industry_code_alternation(raw)
        if unsafe_reason == "ALTERNATIVE_OR_EXCEPTION_RULE"
        else None
    )
    if unsafe_reason and alternation is None:
        return [], [{"code": "UNMAPPED_REQUIREMENT", "raw": raw, "reason": unsafe_reason}]
    diagnostics: list[dict[str, Any]] = []
    requirements: list[QualificationRequirement] = []
    group_key = f"{key_prefix}-GROUP"

    # Only a single explicit code can replace an industry/registration name.
    # Multiple codes need their AND/OR relationship resolved before mapping.
    industry_codes = {
        code for group in _INDUSTRY_CODE_RE.findall(_compact(raw))
        for code in re.findall(r"[0-9]{4}", group)
    }
    if not industry_codes:
        # "업종코드 : 1450" 뿐 아니라 "폐기물수집·운반업(1227)" 처럼 업종명 뒤 괄호에
        # 바로 적는 공고가 많다. 업종명이 앞에 붙어 있을 때만 읽는다 — 그냥 네 자리
        # 숫자를 코드로 보면 연도·금액을 업종으로 만든다.
        named = set(_NAMED_INDUSTRY_CODE_RE.findall(_compact(raw)))
        if len(named) == 1:
            industry_codes = named
    if slot_type in {"업종요건", "등록요건"} and len(industry_codes) > 1 and alternation is None:
        return [], [{"code": "UNMAPPED_INDUSTRY", "raw": raw, "reason": "복수 업종코드의 관계를 확인해야 합니다."}]

    def add(
        suffix: str,
        req_type: RequirementType,
        *,
        operator: RequirementOperator | None = None,
        value: int | float | str | None = None,
        unit: str | None = None,
        period_months: float | None = None,
        scope: dict[str, Any] | None = None,
        group_operator: RequirementOperator | str = "ALL_OF",
    ) -> None:
        # 가드 평가를 구조에 새긴다. 판정기·askability 는 이 표시가 있는 요건의 raw 를 다시
        # 읽지 않는다 — ANY_OF 로 담은 '또는' 을 판정기가 또 막던 문제(J14)가 여기서 끝난다.
        assessment = assess_clause(raw, group_operator=str(group_operator))
        requirements.append(
            QualificationRequirement(
                requirement_key=f"{key_prefix}-{suffix}",
                requirement_group_key=group_key,
                group_operator=group_operator,
                notice_version_id=notice_version_id,
                type=req_type,
                operator=operator,
                value=value,
                unit=unit,
                period_months=period_months,
                scope={**(scope or {}), "guard": GUARD_ASSESSED},
                condition_complexity=assessment.complexity,
                raw=raw,
            )
        )

    if alternation is not None:
        # 관계를 줄이지 않고 그대로 담는다 — 코드 하나가 요건 하나, 묶음은 ANY_OF.
        # 판정기는 이 묶음을 "하나라도 충족하면 충족" 으로 읽는다. 안전 가드가 막던
        # 이유(하나로 줄일 수 없다)가 사라지므로 막을 이유도 사라진다.
        for index, code in enumerate(alternation, start=1):
            add(f"INDUSTRY-{index}", "INDUSTRY", operator="MATCH", value=code,
                group_operator="ANY_OF")
        diagnostics.append({
            "code": "INDUSTRY_ALTERNATION",
            "raw": raw,
            "codes": list(alternation),
        })
        return requirements, diagnostics

    if slot_type == "실적요건":
        amount = slot.get("금액_norm") or {}
        period = slot.get("기간_norm") or {}
        period_months = period.get("value") if period.get("parse_status") == "success" else None
        if slot.get("기간_raw") and period_months is None:
            return [], [{"code": "UNMAPPED_PERFORMANCE", "raw": raw, "reason": "기간을 안전하게 정규화하지 못했습니다."}]
        aggregation = "SUM" if re.search(r"합계|합산|누적|총액", raw) else "UNSPECIFIED"

        # [재현 2026-09-15] 급식 실적 조항("1일 평균 800식 이상")에서 정규화기가 0.0333원을
        # 금액으로 만들어 냈다. "실적 금액 >= 0.03원" 은 실적이 하나라도 있으면 무조건
        # 충족이라 틀린 확정 방향이다. 공고의 실적 금액이 만 원 아래일 리 없다 — 그 아래면
        # 금액이 아니라 다른 숫자(식수·인원·비율)를 잘못 읽은 것이므로 판정에 넣지 않는다.
        parsed_amount = amount.get("value") if amount.get("parse_status") == "success" else None
        if parsed_amount is not None and parsed_amount < _MIN_PLAUSIBLE_AMOUNT_KRW:
            diagnostics.append({
                "code": "UNMAPPED_PERFORMANCE",
                "raw": raw,
                "reason": f"금액 {parsed_amount} 은 실적 금액으로 보기 어렵습니다(하한 {_MIN_PLAUSIBLE_AMOUNT_KRW}원).",
            })
            amount = {}
        if amount.get("parse_status") == "success":
            if amount.get("value") is not None:
                add(
                    "AMOUNT",
                    "PERFORMANCE_AMOUNT",
                    operator=amount.get("op"),
                    value=amount.get("value"),
                    unit=amount.get("unit") or "KRW",
                    period_months=period_months,
                    scope=_performance_scope(slot, aggregation=aggregation),
                )
            elif amount.get("range"):
                amount_range = dict(amount["range"])
                add(
                    "AMOUNT",
                    "PERFORMANCE_AMOUNT",
                    operator="RANGE",
                    unit=amount.get("unit") or "KRW",
                    period_months=period_months,
                    scope={
                        **_performance_scope(slot, aggregation=aggregation),
                        "min": amount_range.get("min"),
                        "min_operator": amount_range.get("min_op"),
                        "max": amount_range.get("max"),
                        "max_operator": amount_range.get("max_op"),
                    },
                )

        count_source = (slot.get("건수_raw") or raw).strip()
        count_match = _COUNT_RE.search(count_source)
        if count_match:
            add(
                "COUNT",
                "PERFORMANCE_COUNT",
                operator=_op(count_match.group(2)) or ">=",
                value=int(count_match.group(1)),
                unit="COUNT",
                period_months=period_months,
                scope=_performance_scope(slot),
            )

        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add(
                "EXPERIENCE",
                "EXPERIENCE_FIELD",
                operator="MATCH",
                value=experience_field,
                period_months=period_months,
                scope={"source": "PERFORMANCE", **_performance_scope(slot)},
            )

        if not requirements:
            diagnostics.append({"code": "UNMAPPED_PERFORMANCE", "raw": raw})

    elif slot_type == "경험분야요건":
        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add("EXPERIENCE", "EXPERIENCE_FIELD", operator="MATCH", value=experience_field)
        else:
            diagnostics.append({"code": "UNMAPPED_EXPERIENCE_FIELD", "raw": raw})

    elif slot_type == "업종요건":
        industry = (slot.get("업종_raw") or "").strip()
        if industry_codes:
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)), scope={"industry_name": industry} if industry else {})
        elif industry:
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=industry)
        else:
            diagnostics.append({"code": "UNMAPPED_INDUSTRY", "raw": raw})

    elif slot_type == "지역요건":
        # [재현 2026-09-15, 우치공원 1/5] 모델이 지역값에 "…에 소재한 업체" 꼬리를 붙여 낼 때가
        # 있다. 판정은 포함 비교라 통과하지만 값이 달라져 실행마다 요건 지문이 갈렸다. 지역명은
        # 행정구역 이름이지 문장이 아니다 — 꼬리를 뗀다.
        region = _REGION_TAIL_RE.sub("", (slot.get("지역_raw") or "").strip()).strip()
        if region:
            add("REGION", "REGION", operator="MATCH", value=region)
        else:
            diagnostics.append({"code": "UNMAPPED_REGION", "raw": raw})

    elif slot_type == "인력요건":
        headcount = slot.get("인원_norm") or {}
        role = (slot.get("인력역할_raw") or "").strip()
        if headcount.get("parse_status") == "success" and headcount.get("value") is not None:
            add(
                "STAFF",
                "STAFF",
                operator=headcount.get("op") or ">=",
                value=headcount.get("value"),
                unit=headcount.get("unit") or "PERSON",
                scope={"role": role} if role else {},
            )
        elif role:
            add("STAFF", "STAFF", operator="MATCH", value=role, scope={"role": role})
        else:
            diagnostics.append({"code": "UNMAPPED_STAFF", "raw": raw})

    elif slot_type in {"인증요건", "면허요건", "등록요건"}:
        name = (slot.get("등록인증_raw") or "").strip()
        issuer = (slot.get("발급기관_raw") or "").strip()
        kind = {
            "인증요건": "CERTIFICATION",
            "면허요건": "LICENSE",
            "등록요건": "REGISTRATION",
        }[slot_type]
        # [재현 2026-09-15] 등록요건뿐 아니라 인증·면허로 분류돼도 원문에 업종코드가 하나
        # 있으면 업종 요건일 수 있다. 실측에서 같은 "영업신고(업종코드 : 1450)" 조항을 모델이
        # 인증요건으로 낸 실행이 있었고, 그때 INDUSTRY 1450 이 아예 안 만들어져 인증 쪽에서
        # 미달이 났다.
        #
        # 단, **값이 업종명이나 등록 행위 모양일 때만**이다. "업종코드: 1468 업체는 ISO 27001
        # 인증 보유" 처럼 같은 조항에 진짜 인증이 적혀 있으면 그 인증은 별개 요건이다 —
        # 코드가 있다고 그것을 업종으로 바꾸면 ISO 27001 을 삼킨다(test_canonicalize 가 막는다).
        looks_like_industry = bool(name) and (
            _INDUSTRY_NAME_VALUE_RE.fullmatch(_squash_name(name))
            or _REGISTRATION_ACT_VALUE_RE.fullmatch(_squash_name(name))
        )
        size_alias = company_size_alias(name) if is_company_size_certificate_name(name) else None
        if industry_codes and (slot_type == "등록요건" or looks_like_industry):
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)), scope={"kind": kind, "industry_name": name})
        elif size_alias:
            # [재현 2026-09-15] "소기업·소상공인확인서" 는 인증이 아니라 회사 규모의 증빙 서류다.
            # 인증 요건으로 두면 회사 인증 목록과 대조돼 SMALL 회사가 미달을 받는다 —
            # 1450 업종/등록 이중분류와 같은 틀린 확정 경로. 골든셋은 COMPANY_SIZE 로 본다.
            add("COMPANY_SIZE", "COMPANY_SIZE", operator="MATCH", value=size_alias)
            diagnostics.append({
                "code": "COMPANY_SIZE_FROM_CERTIFICATE",
                "raw": raw,
                "certificate_name": name,
                "company_size": size_alias,
            })
        elif name:
            scope: dict[str, Any] = {"kind": kind}
            if issuer:
                scope["issuer"] = issuer
            add(
                "CERT",
                "REGISTRATION_CERTIFICATION",
                operator="MATCH",
                value=name,
                scope=scope,
            )
        else:
            diagnostics.append({"code": "UNMAPPED_REGISTRATION_CERTIFICATION", "raw": raw})

    elif slot_type == "기업규모요건":
        company_size = (slot.get("기업규모_raw") or "").strip()
        if company_size:
            # 이어 붙인 규모 낱말("중·소기업·소상공인")은 판정기의 alias 표에 없어 문자열
            # 비교로 떨어진다 — 합집합이 한 낱말과 같으면 그 낱말로 정규화한다(위 주석).
            add(
                "COMPANY_SIZE",
                "COMPANY_SIZE",
                operator="MATCH",
                value=company_size_alias(company_size) or company_size,
                scope={"restriction": "EXCLUDE"}
                if _SIZE_EXCLUSION_RE.search(raw)
                else {},
            )
        else:
            diagnostics.append({"code": "UNMAPPED_COMPANY_SIZE", "raw": raw})

    elif slot_type == "기타요건":
        # [재현 2026-09-14] '기타요건' 은 통째로 버려졌다. 그런데 모델은 업종코드가 박힌
        # 조항을 '기타요건' 으로 분류하는 일이 잦다 — 구내식당 공고의 "영업신고(업종코드 :
        # 1450)를 하여 집단급식소 영업이 가능한 법인사업자" 가 그랬고, 골든셋은 이것을
        # INDUSTRY 1450 으로 본다. 분류는 실행마다 흔들려도 **원문의 숫자는 흔들리지 않는다.**
        # 그래서 코드가 직접 읽어 살린다.
        salvaged = salvage_closed_identifier(raw)
        if salvaged is None:
            diagnostics.append({"code": "UNMAPPED_REQUIREMENT", "raw": raw})
        else:
            salvaged_type, salvaged_value = salvaged
            add(salvaged_type, salvaged_type, operator="MATCH", value=salvaged_value)
            diagnostics.append({
                "code": "SALVAGED_CLOSED_IDENTIFIER",
                "raw": raw,
                "salvaged_type": salvaged_type,
                "value": salvaged_value,
            })
    else:
        diagnostics.append({"code": "UNKNOWN_LEGACY_TYPE", "type": slot_type, "raw": raw})

    return requirements, diagnostics
