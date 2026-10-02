"""Qualification requirements that the notice API states directly.

Before any document is parsed, the 나라장터 notice record already answers part of
the question: which regions may bid, which licences are demanded, which industry
registrations are accepted. Reading those fields costs one API call and no model,
so it is the cheapest first pass there is.

Rather than judging them separately, the fields are converted into the same
`QualificationRequirement` objects that document extraction produces. One judge,
one contract, one reason format — and the follow-up loop works on them for free.

Field names differ across the notice endpoints, which is the trap here. A 용역
notice carries `indstrytyLmtYn` ("is there an industry restriction?") but not the
list of permitted industries, while 공사 and 물품 notices carry `lcnsLmtNm` and
`permsnIndstrytyList` with the actual values. So:

- A field naming a concrete restriction becomes a requirement.
- A flag saying a restriction exists **without saying what it is** becomes a
  diagnostic, never a requirement. Judging "이 공고는 업종제한이 있다" against a
  profile would be deciding with no criterion in hand.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from bidengine.contracts import QualificationRequirement


# Fields that name an actual region a bidder must be in.
_REGION_FIELDS = (
    "prtcptPsblRgnNm",  # 참가가능지역명
    "prtcptLmtRgnNm",  # 참가제한지역명
)

# NOT a region. `rgnLmtBidLocplcJdgmBssNm` holds values like "본사또는참여지사소재지":
# it says *how* an office location is judged when a region restriction applies,
# never *which* region is permitted. Measured over 300 live notices it is set on
# 23% of them, so reading it as a region name would manufacture a false
# UNSATISFIED for roughly a quarter of everything the system sees.
_REGION_BASIS_FIELD = "rgnLmtBidLocplcJdgmBssNm"
_JOINT_REGION_FIELDS = ("jntcontrctDutyRgnNm1", "jntcontrctDutyRgnNm2", "jntcontrctDutyRgnNm3")

_LICENCE_FIELDS = ("lcnsLmtNm",)  # 면허제한명 — "정보통신공사업/0036" 형태
_INDUSTRY_LIST_FIELDS = ("permsnIndstrytyList",)  # 허용업종목록

_NO_LIMIT_TOKENS = ("전국", "제한없음", "제한 없음", "해당없음", "해당 없음")

# "정보통신공사업/0036" or "[업종명/코드,업종명/코드]"
_NAME_CODE_RE = re.compile(r"([^,\[\]/]+)/(\d+)")

_PRICE_FIELDS = {
    "estimated_price": ("presmptPrce",),  # 추정가격
    "assigned_budget": ("asignBdgtAmt",),  # 배정예산액
    "base_amount": ("bssamt", "bssAmt"),  # 기초금액
}


class NoticePriceInfo(BaseModel):
    """Contract price figures, shown as-is.

    Display only. These never feed a qualification verdict: an estimated price
    says what the work is worth, not whether this company may bid for it.
    """

    estimated_price: int | None = None
    assigned_budget: int | None = None
    base_amount: int | None = None
    vat: int | None = None
    currency: str = "KRW"

    def as_display_lines(self) -> list[str]:
        labels = (
            ("추정가격", self.estimated_price),
            ("배정예산", self.assigned_budget),
            ("기초금액", self.base_amount),
            ("부가세", self.vat),
        )
        return [f"{label} {value:,}원" for label, value in labels if value is not None]


class NoticeFacts(BaseModel):
    """The parts of a notice record a person reads first."""

    notice_no: str | None = None
    notice_order: str | None = None
    title: str | None = None
    institution: str | None = None
    demand_institution: str | None = None
    business_type_name: str | None = None
    contract_method: str | None = None
    bid_close_at: str | None = None
    opening_at: str | None = None
    classification: str | None = None
    detail_url: str | None = None
    document_urls: list[str] = Field(default_factory=list)
    price: NoticePriceInfo = Field(default_factory=NoticePriceInfo)


def _value(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        raw = item.get(key)
        if raw not in (None, "", []):
            text = str(raw).strip()
            if text:
                return text
    return None


def _int_value(item: dict[str, Any], *keys: str) -> int | None:
    text = _value(item, *keys)
    if text is None:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _is_yes(item: dict[str, Any], key: str) -> bool:
    return (_value(item, key) or "").upper() == "Y"


def _name_code_pairs(text: str | None) -> list[tuple[str, str]]:
    """Pull "이름/코드" pairs out of the packed strings these fields use."""
    if not text:
        return []
    return [(name.strip(), code) for name, code in _NAME_CODE_RE.findall(text) if name.strip()]


def extract_notice_facts(item: dict[str, Any]) -> NoticeFacts:
    """Read the display-facing fields, including price."""
    document_urls = [
        url
        for url in (_value(item, f"ntceSpecDocUrl{index}") for index in range(1, 11))
        if url
    ]
    standard_document = _value(item, "stdNtceDocUrl")
    if standard_document:
        document_urls.insert(0, standard_document)

    return NoticeFacts(
        notice_no=_value(item, "bidNtceNo"),
        notice_order=_value(item, "bidNtceOrd"),
        title=_value(item, "bidNtceNm"),
        institution=_value(item, "ntceInsttNm"),
        demand_institution=_value(item, "dminsttNm"),
        business_type_name=_value(item, "srvceDivNm", "pubPrcrmntLrgClsfcNm"),
        contract_method=_value(item, "cntrctCnclsMthdNm"),
        bid_close_at=_value(item, "bidClseDt"),
        opening_at=_value(item, "opengDt"),
        classification=_value(item, "pubPrcrmntClsfcNm", "pubPrcrmntMidClsfcNm"),
        detail_url=_value(item, "bidNtceDtlUrl", "bidNtceUrl"),
        document_urls=document_urls,
        price=NoticePriceInfo(
            estimated_price=_int_value(item, *_PRICE_FIELDS["estimated_price"]),
            assigned_budget=_int_value(item, *_PRICE_FIELDS["assigned_budget"]),
            base_amount=_int_value(item, *_PRICE_FIELDS["base_amount"]),
            vat=_int_value(item, "VAT", "indutyVAT"),
        ),
    )


def build_notice_requirements(
    item: dict[str, Any],
    *,
    notice_version_id: str,
    key_prefix: str = "NOTICE-FIELD",
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """Convert notice API fields into canonical requirements plus diagnostics.

    Returns `(requirements, diagnostics)`. A diagnostic is what a restriction
    becomes when the API says it exists but not what it is — the notice document
    has to be read for those, and saying so is more useful than guessing.
    """
    requirements: list[QualificationRequirement] = []
    diagnostics: list[dict[str, Any]] = []
    sequence = 0

    def add(
        suffix: str,
        requirement_type: str,
        value: str,
        raw: str,
        *,
        scope: dict[str, Any] | None = None,
    ) -> None:
        nonlocal sequence
        sequence += 1
        requirements.append(
            QualificationRequirement(
                requirement_key=f"{key_prefix}-{sequence:02d}-{suffix}",
                notice_version_id=notice_version_id,
                type=requirement_type,  # type: ignore[arg-type]
                operator="MATCH",
                value=value,
                raw=raw,
                scope={"origin": "NOTICE_API_FIELD", **(scope or {})},
            )
        )

    # ── region ───────────────────────────────────────────────────────────
    region = _value(item, *_REGION_FIELDS)
    joint_regions = [
        value for value in (_value(item, key) for key in _JOINT_REGION_FIELDS) if value
    ]
    if region and not any(token in region for token in _NO_LIMIT_TOKENS):
        add("REGION", "REGION", region, f"참가가능지역: {region}")
    elif joint_regions:
        joined = ", ".join(joint_regions)
        add(
            "REGION",
            "REGION",
            joined,
            f"지역의무공동계약 대상지역: {joined}",
            scope={"joint_contract": True},
        )
    elif region:
        diagnostics.append(
            {
                "code": "NO_REGION_LIMIT",
                "severity": "INFO",
                "message": f"지역 제한 없음 (공고값: {region})",
            }
        )

    region_basis = _value(item, _REGION_BASIS_FIELD)
    if region_basis and not requirements:
        diagnostics.append(
            {
                "code": "REGION_LIMIT_WITHOUT_DETAIL",
                "severity": "WARNING",
                "message": (
                    f"지역제한 공고입니다(판단기준: {region_basis}). 다만 API 응답에 "
                    f"허용 지역이 없어 어느 지역인지는 공고문에서 확인해야 합니다."
                ),
            }
        )

    # ── licence / registration ───────────────────────────────────────────
    licence = _value(item, *_LICENCE_FIELDS)
    if licence:
        for name, code in _name_code_pairs(licence) or [(licence, "")]:
            add(
                "LICENCE",
                "REGISTRATION_CERTIFICATION",
                name,
                f"면허제한: {licence}",
                scope={"kind": "LICENSE", "code": code} if code else {"kind": "LICENSE"},
            )

    # ── industry registration ────────────────────────────────────────────
    industry_list = _value(item, *_INDUSTRY_LIST_FIELDS)
    industry_pairs = _name_code_pairs(industry_list)
    if industry_pairs:
        for name, code in industry_pairs:
            add(
                "INDUSTRY",
                "INDUSTRY",
                code or name,
                f"허용업종: {industry_list}",
                scope={"industry_name": name, "industry_code": code},
            )
    elif _is_yes(item, "indstrytyLmtYn"):
        # The 용역 endpoint says a restriction exists but never says which
        # industries are permitted. Turning that into a requirement would mean
        # judging against a criterion we do not have.
        diagnostics.append(
            {
                "code": "INDUSTRY_LIMIT_WITHOUT_DETAIL",
                "severity": "WARNING",
                "message": (
                    "공고에 업종제한이 있으나 API 응답에 허용업종 목록이 없습니다 "
                    "— 공고문에서 확인해야 합니다."
                ),
            }
        )

    # ── restrictions the API only flags ──────────────────────────────────
    if _is_yes(item, "bidPrtcptLmtYn"):
        diagnostics.append(
            {
                "code": "PARTICIPATION_LIMIT",
                "severity": "WARNING",
                "message": "입찰참가 제한이 설정된 공고입니다 — 공고문에서 제한 내용을 확인하세요.",
            }
        )
    if _is_yes(item, "prdctClsfcLmtYn"):
        diagnostics.append(
            {
                "code": "PRODUCT_CLASS_LIMIT",
                "severity": "INFO",
                "message": "물품분류 제한이 설정된 공고입니다.",
            }
        )
    if _is_yes(item, "arsltCmptYn"):
        diagnostics.append(
            {
                "code": "PERFORMANCE_COMPETITION",
                "severity": "INFO",
                "message": "실적 경쟁이 적용되는 공고입니다 — 실적 요건은 공고문을 확인하세요.",
            }
        )

    registration_type = _value(item, "rgstTyNm")
    if registration_type:
        diagnostics.append(
            {
                "code": "REGISTRATION_TYPE",
                "severity": "INFO",
                "message": f"요구 등록유형: {registration_type}",
            }
        )

    return requirements, diagnostics
