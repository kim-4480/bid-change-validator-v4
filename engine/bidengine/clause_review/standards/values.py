"""Reading the comparison thresholds out of the published rules themselves.

The figures a notice is checked against — 하자보수 1년, 지체상금 상한 100분의 30 —
are **not written in this codebase**. They are extracted from the rule text on
every run, and the only thing kept in code is an anchor saying where in the text
to look.

This is not tidiness. If the number lived in code as well as in the rules, then
an amendment would leave the two disagreeing, and the code would keep deciding
confidently on the old threshold. Being confidently wrong is the worst failure
this pipeline can have.

The project's principles apply directly:

- Extraction is a regex anchor plus `app.ai.normalization`. No model is involved.
- **A failed extraction never falls back to an older number.** The rule is
  reported as UNDETERMINED instead. Withholding a judgment beats issuing one with
  no source behind it.
- `recorded` is a tripwire only and is never used to decide anything. When the
  extracted value differs from it, the rules have most likely been amended and
  the run says so.
"""

from __future__ import annotations

import re
from typing import Any

from bidengine.normalization import extract_values
from bidengine.clause_review.standards.index import find_clause


# Which terms govern a contract depends on what kind of contract it is, at two
# levels. 용역, 공사 and 물품 each have their own 계약예규; and 용역계약일반조건 is
# itself chaptered, with 소프트웨어용역 and 건설사업관리 getting their own chapters
# on top of the common one.
#
# So a rule is not one clause but a set of scope-tagged variants. Judging a 물품
# notice against 제58조 (a 소프트웨어용역 clause) is how a rule becomes confidently
# wrong, which is the failure this package exists to avoid.
CONTRACT_SCOPES = ("COMMON", "SOFTWARE", "CM", "GOODS", "CONSTRUCTION")

SCOPE_LABELS = {
    "COMMON": "용역계약일반조건 제2장 일반용역계약조건(공통)",
    "CM": "용역계약일반조건 제3장 시공 단계의 건설사업관리용역",
    "SOFTWARE": "용역계약일반조건 제4장 소프트웨어용역 계약조건",
    "GOODS": "물품구매(제조)계약일반조건",
    "CONSTRUCTION": "공사계약일반조건",
}

# Where a scope looks when it has no clause of its own. 소프트웨어용역 and
# 건설사업관리 are chapters *inside* 용역계약일반조건, so they inherit its common
# chapter. 공사 and 물품 are separate 예규 and inherit nothing — falling back to
# 용역 there would reintroduce exactly the error this table exists to prevent.
SCOPE_FALLBACK = {
    "SOFTWARE": "COMMON",
    "CM": "COMMON",
    "COMMON": None,
    "GOODS": None,
    "CONSTRUCTION": None,
}

# Each rule lists its variants **most specific first**, so that resolving with no
# scope at all (introspection, tests) still picks the narrowest known clause.
#
# scope   : which contracts this clause governs. "COMMON" applies to all of them.
# anchor  : regex selecting the *short span* of rule text holding the figure.
#           Group 1 is that span, and only it is handed to the normalizer.
#           Passing the whole clause would pick up unrelated numbers from the
#           same article (제21조, 100분의 50 …), so anchors stay narrow.
# unit    : the unit this rule compares in; only values in it are accepted.
# recorded: the value at the time this spec was written (2026-04-30 예규 제149호).
#           Tripwire only.
# note    : which sentence the figure lives in, so a person knows where to look
#           when an anchor stops matching.
SPECS: dict[str, dict[str, Any]] = {
    # 하자담보 has no 제2장 counterpart: the 예규 states it only for 소프트웨어용역.
    # A 물품 or 공사 notice therefore has no standard here to be measured against,
    # and this rule stays out of its review rather than borrowing the SW figure.
    "warranty_period": {
        "variants": [
            {
                "scope": "SOFTWARE",
                "source": "용역계약일반조건",
                "clause_no": "58조",
                "ref": "용역계약일반조건 제58조제1항",
                "desc_template": "인수 확인 후 {value}",
                "anchor": r"종료를\s*확인한\s*후\s*([^(]{1,12}?)간",
                "unit": "MONTH",
                "recorded": 12,
                "note": "제58조제1항 '사업의 종료를 확인한 후 1년간 ... 보수책임'",
            },
        ],
    },
    "warranty_bond_rate": {
        "variants": [
            {
                "scope": "SOFTWARE",
                "source": "용역계약일반조건",
                "clause_no": "59조",
                "ref": "용역계약일반조건 제59조제1항",
                "desc_template": "계약금액의 {value}",
                "anchor": r"하자보수보증금율\s*\(\s*([^,)]{1,20})",
                "unit": "PERCENT",
                "recorded": 2,
                "note": "제59조제1항 '하자보수보증금율(100분의 2, ...)'",
            },
        ],
    },
    # 지체상금 has two figures that must not be confused: how much accrues per day
    # of delay (요율), and the ceiling the total may not pass (상한). They live in
    # different documents and a notice can depart from either independently.
    #
    # 요율: 용역계약일반조건 제55조 does not state a number — it points at
    # 시행규칙 제75조, so that is where the figure is read from. 제75조 lists a rate
    # per contract kind; 제3호 is 용역, which is every contract this pipeline sees.
    "penalty_rate": {
        "variants": [
            {
                "scope": "COMMON",
                "source": "국가계약법 시행규칙",
                "clause_no": "75조",
                "ref": "국가계약법 시행규칙 제75조제3호",
                "desc_template": "지연 1일당 계약금액의 {value}",
                # "및 기타:" appears only in 제3호, which is the 용역 rate.
                "anchor": r"및\s*기타\s*:\s*(\d*\s*천분의\s*\d+(?:\.\d+)?)",
                "unit": "PERCENT",
                "recorded": 0.125,
                "note": "제75조제3호 '물품의 수리ㆍ가공ㆍ대여, 용역 … 및 기타: 1천분의 1.25'",
            },
            # 제75조 sets a different rate per kind of contract, so 공사 and 물품
            # read their own 호 out of the same article.
            {
                "scope": "CONSTRUCTION",
                "source": "국가계약법 시행규칙",
                "clause_no": "75조",
                "ref": "국가계약법 시행규칙 제75조제1호",
                "desc_template": "지연 1일당 계약금액의 {value}",
                "anchor": r"1\.\s*공사\s*:\s*(\d*\s*천분의\s*\d+(?:\.\d+)?)",
                "unit": "PERCENT",
                "recorded": 0.05,
                "note": "제75조제1호 '공사: 1천분의 0.5'",
            },
            {
                "scope": "GOODS",
                "source": "국가계약법 시행규칙",
                "clause_no": "75조",
                "ref": "국가계약법 시행규칙 제75조제2호",
                "desc_template": "지연 1일당 계약금액의 {value}",
                # The 단서 lowers it to 0.5 for design-and-build 물품; the headline
                # rate is what a notice is compared against.
                "anchor": r"2\.\s*물품의\s*제조[^:]{0,200}?:\s*(\d*\s*천분의\s*\d+(?:\.\d+)?)",
                "unit": "PERCENT",
                "recorded": 0.075,
                "note": "제75조제2호 '물품의 제조ㆍ구매 …: 1천분의 0.75'",
            },
        ],
    },
    # 상한: 제55조 defers the cap to 제18조, so it is common to every 용역 contract.
    "penalty_cap": {
        "variants": [
            {
                "scope": "COMMON",
                "source": "용역계약일반조건",
                "clause_no": "18조",
                "ref": "용역계약일반조건 제18조제1항",
                "desc_template": "지체상금 총액은 계약금액의 {value} 이내",
                "anchor": r"초과하는\s*경우에는\s*([^으]{1,15}?)으로\s*한다",
                "unit": "PERCENT",
                "recorded": 30,
                "note": "제18조제1항 단서 '100분의 30을 초과하는 경우에는 100분의 30으로 한다'",
            },
            # 공사·물품 word the ceiling identically, so only the article moves.
            {
                "scope": "CONSTRUCTION",
                "source": "공사계약일반조건",
                "clause_no": "25조",
                "ref": "공사계약일반조건 제25조제1항",
                "desc_template": "지체상금 총액은 계약금액의 {value} 이내",
                "anchor": r"초과하는\s*경우에는\s*([^으]{1,15}?)으로\s*한다",
                "unit": "PERCENT",
                "recorded": 30,
                "note": "제25조제1항 단서 '100분의 30을 초과하는 경우에는 100분의 30으로 한다'",
            },
            {
                "scope": "GOODS",
                "source": "물품구매(제조)계약일반조건",
                "clause_no": "24조",
                "ref": "물품구매(제조)계약일반조건 제24조제1항",
                "desc_template": "지체상금 총액은 계약금액의 {value} 이내",
                "anchor": r"초과하는\s*경우에는\s*([^으]{1,15}?)으로\s*한다",
                "unit": "PERCENT",
                "recorded": 30,
                "note": "제24조제1항 단서 '100분의 30을 초과하는 경우에는 100분의 30으로 한다'",
            },
        ],
    },
    "inspection_period": {
        "variants": [
            {
                "scope": "COMMON",
                "source": "용역계약일반조건",
                "clause_no": "20조",
                "ref": "용역계약일반조건 제20조제2항",
                "desc_template": "통지받은 날부터 {value} 이내 검사",
                "anchor": r"통지를\s*받은\s*날부터\s*([^,]{1,12}?)\s*이내",
                "unit": "MONTH",
                "recorded": 14 / 30,
                "note": "제20조제2항 '통지를 받은 날부터 14일 이내에 ... 검사'",
            },
            {
                "scope": "CONSTRUCTION",
                "source": "공사계약일반조건",
                "clause_no": "27조",
                "ref": "공사계약일반조건 제27조제2항",
                "desc_template": "통지받은 날부터 {value} 이내 검사",
                "anchor": r"통지를\s*받은\s*날로부터\s*([^,]{1,12}?)\s*이내",
                "unit": "MONTH",
                "recorded": 14 / 30,
                "note": "제27조제2항 '통지를 받은 날로부터 14일 이내에 ... 검사'",
            },
            {
                "scope": "GOODS",
                "source": "물품구매(제조)계약일반조건",
                "clause_no": "19조",
                "ref": "물품구매(제조)계약일반조건 제19조제3항",
                "desc_template": "통지받은 날부터 {value} 이내 검사",
                # 물품 phrases it as "그 날로부터", the day the notice was received.
                "anchor": r"그\s*날로부터\s*([^,]{1,12}?)\s*이내",
                "unit": "MONTH",
                "recorded": 14 / 30,
                "note": "제19조제3항 '통지를 받은 때에는 ... 그 날로부터 14일 이내에 ... 검사'",
            },
        ],
    },
    "termination_threshold": {
        "variants": [
            {
                "scope": "COMMON",
                "source": "용역계약일반조건",
                "clause_no": "31조",
                "ref": "용역계약일반조건 제31조제1항",
                "desc_template": "계약금액 {value} 이상 감소 시 해제·해지 가능",
                "anchor": r"계약금액이\s*(.{1,15}?)\s*이상\s*감소",
                "unit": "PERCENT",
                "recorded": 40,
                "note": "제31조제1항제1호 '계약금액이 100분의 40이상 감소되었을 때'",
            },
            {
                "scope": "CONSTRUCTION",
                "source": "공사계약일반조건",
                "clause_no": "46조",
                "ref": "공사계약일반조건 제46조제1항제1호",
                "desc_template": "계약금액 {value} 이상 감소 시 해제·해지 가능",
                "anchor": r"계약금액이\s*(.{1,15}?)\s*이상\s*감소",
                "unit": "PERCENT",
                "recorded": 40,
                "note": "제46조제1항제1호 '계약금액이 100분의 40이상 감소되었을 때'",
            },
            # 물품구매(제조)계약일반조건 lists grounds for termination but sets no
            # reduction threshold, so a 물품 notice has nothing to be measured
            # against here and this rule stays out of its review.
        ],
    },
    # 제27조제2항 sets the deadline at 5일 from the request. Its proviso lets the
    # parties agree an extension of at most a further 5일, so a notice above the
    # standard is a thing to look at rather than a breach — which is what
    # NEEDS_REVIEW already means. 제26조 puts 기성대가 on the same 5일.
    "payment_period": {
        "variants": [
            {
                "scope": "COMMON",
                "source": "용역계약일반조건",
                "clause_no": "27조",
                "ref": "용역계약일반조건 제27조제2항",
                "desc_template": "지급청구를 받은 날부터 {value} 이내 지급",
                "anchor": r"청구를\s*받은\s*(?:날|때)로?부터\s*(\d+\s*일)",
                "unit": "MONTH",
                "recorded": 5 / 30,
                "note": "제27조제2항 '그 청구를 받은 날로부터 5일 ... 이내에 그 대가를 지급'",
            },
            # 공사·물품 word the deadline identically; only the article moves.
            {
                "scope": "CONSTRUCTION",
                "source": "공사계약일반조건",
                "clause_no": "40조",
                "ref": "공사계약일반조건 제40조제2항",
                "desc_template": "지급청구를 받은 날부터 {value} 이내 지급",
                "anchor": r"청구를\s*받은\s*(?:날|때)로?부터\s*(\d+\s*일)",
                "unit": "MONTH",
                "recorded": 5 / 30,
                "note": "제40조제2항 '그 청구를 받은 날로부터 5일 ... 이내에 그 대가를 지급'",
            },
            {
                "scope": "GOODS",
                "source": "물품구매(제조)계약일반조건",
                "clause_no": "22조",
                "ref": "물품구매(제조)계약일반조건 제22조제2항",
                "desc_template": "지급청구를 받은 날부터 {value} 이내 지급",
                "anchor": r"청구를\s*받은\s*(?:날|때)로?부터\s*(\d+\s*일)",
                "unit": "MONTH",
                "recorded": 5 / 30,
                "note": "제22조제2항 '그 청구를 받은 날로부터 5일 ... 이내에 그 대가를 지급'",
            },
        ],
    },
    # Wording rules: there is no figure to compare. All that is checked is that
    # the standard wording is still in the rule text, so that an amendment
    # removing the joint-ownership principle does not go unnoticed.
    #
    # 제35조의2 is the 공통 counterpart added in 2014. It states joint ownership
    # but leaves the share split to 제56조 ("기타사항은 제56조를 준용"), so its
    # anchor stops at ownership and its description says only that much.
    "ip_ownership": {
        "variants": [
            {
                "scope": "SOFTWARE",
                "source": "용역계약일반조건",
                "clause_no": "56조",
                "ref": "용역계약일반조건 제56조제1항",
                "desc_template": "발주기관·계약상대자 공동소유, 지분 균등",
                "anchor": r"(공동으로\s*소유하며[^.]{0,40}지분은\s*균등)",
                "unit": None,
                "recorded": None,
                "note": "제56조제1항 '발주기관과 계약상대자가 공동으로 소유하며 ... 지분은 균등'",
            },
            {
                "scope": "COMMON",
                "source": "용역계약일반조건",
                "clause_no": "35조의2",
                "ref": "용역계약일반조건 제35조의2제1항",
                "desc_template": "발주기관·계약상대자 공동소유",
                "anchor": r"(공동으로\s*소유한다)",
                "unit": None,
                "recorded": None,
                "note": "제35조의2제1항 '발주기관과 계약상대자가 공동으로 소유한다'",
            },
            {
                "scope": "GOODS",
                "source": "물품구매(제조)계약일반조건",
                "clause_no": "29조의2",
                "ref": "물품구매(제조)계약일반조건 제29조의2",
                "desc_template": "발주기관·계약상대자 공동소유, 지분 균등",
                "anchor": r"(공동으로\s*소유하며[^.]{0,40}지분은\s*균등)",
                "unit": None,
                "recorded": None,
                "note": "제29조의2 '공동으로 소유하며, 별도의 정함이 없는 한 지분은 균등'",
            },
            # 공사계약일반조건 has no intellectual-property clause at all, so this
            # rule does not review 공사 notices.
        ],
    },
    # 제23조 does not cap what may be claimed; it draws a line at fault. The
    # contractor bears harm arising in performance, **except** harm they are not
    # responsible for, which is the authority's. So what is checked is that the
    # exception is still there — a notice that erases it has widened liability
    # beyond the standard even though no figure changed.
    "liability_scope": {
        "variants": [
            {
                "scope": "COMMON",
                "source": "용역계약일반조건",
                "clause_no": "23조",
                "ref": "용역계약일반조건 제23조제1항",
                "desc_template": "계약상대자의 책임 없는 손해는 발주기관 부담",
                "anchor": r"(책임없는\s*사유로\s*인하여\s*발생한\s*경우에는\s*발주기관의\s*부담)",
                "unit": None,
                "recorded": None,
                "note": (
                    "제23조제1항 단서 '그 손해가 계약상대자의 책임없는 사유로 인하여 "
                    "발생한 경우에는 발주기관의 부담으로 한다'"
                ),
            },
            {
                "scope": "CONSTRUCTION",
                "source": "공사계약일반조건",
                "clause_no": "31조",
                "ref": "공사계약일반조건 제31조제1항",
                "desc_template": "계약상대자의 책임 없는 손해는 발주기관 부담",
                # 공사 says "발생한 손해는", 용역 says "발생한 경우에는".
                "anchor": r"(책임없는\s*사유로\s*인하여\s*발생한\s*손해는\s*발주기관의\s*부담)",
                "unit": None,
                "recorded": None,
                "note": (
                    "제31조제1항 단서 '계약상대자의 책임없는 사유로 인하여 발생한 "
                    "손해는 발주기관의 부담으로 한다'"
                ),
            },
            # 물품구매(제조)계약일반조건 has no general-damages clause, so this rule
            # does not review 물품 notices.
        ],
    },
}

ResolveStatus = str
# "ok" | "out_of_scope" | "clause_missing" | "anchor_failed" | "normalize_failed"


def select_variant(
    rule_id: str, contract_scope: str | None
) -> dict[str, Any] | None:
    """The clause that governs this rule for this kind of contract.

    `None` for `contract_scope` means "do not filter" — the narrowest variant is
    returned. That is for introspection; a real review always passes a scope.

    Returns None when the rules state nothing for this contract kind, which is a
    deliberate silence rather than a failure: the rule simply does not apply.
    """
    variants = SPECS[rule_id]["variants"]
    if contract_scope is None:
        return variants[0]

    scope: str | None = contract_scope
    while scope is not None:
        for variant in variants:
            if variant["scope"] == scope:
                return variant
        scope = SCOPE_FALLBACK.get(scope)
    return None


def format_value(value: float, unit: str | None) -> str:
    """Render a figure the way the rules phrase it, for display in a report."""
    if unit == "MONTH":
        if abs(value - round(value)) < 1e-6:
            months = int(round(value))
            if months % 12 == 0 and months >= 12:
                return f"{months // 12}년"
            return f"{months}개월"
        return f"{round(value * 30)}일"
    if unit == "PERCENT":
        return f"100분의 {value:g}"
    return str(value)


def resolve_standard_value(
    rule_id: str,
    clauses: list[dict[str, Any]],
    *,
    contract_scope: str | None = None,
) -> dict[str, Any]:
    """Extract one rule's threshold from the rule text.

    Returns `status` "ok" only when a usable value was actually read. Every other
    status leaves `value` at None, and the caller must not judge on it.

    Status "out_of_scope" is not an error: the published rules simply say nothing
    about this matter for this kind of contract, so the rule has no business
    reviewing the notice at all.
    """
    spec = select_variant(rule_id, contract_scope)
    if spec is None:
        return {
            "rule_id": rule_id,
            "status": "out_of_scope",
            "value": None,
            "unit": None,
            "ref": None,
            "desc": None,
            "raw": None,
            "clause": None,
            "drift": None,
            "scope": contract_scope,
            "notes": (
                f"{SCOPE_LABELS.get(contract_scope, contract_scope)} 계약에는 "
                f"이 항목에 대응하는 예규 조문이 없어 검토 대상이 아닙니다"
            ),
        }

    clause = find_clause(clauses, spec["source"], spec["clause_no"])
    resolved: dict[str, Any] = {
        "rule_id": rule_id,
        "status": "clause_missing",
        "value": None,
        "unit": spec["unit"],
        "ref": spec["ref"],
        "desc": spec["desc_template"].replace("{value}", "?"),
        "raw": None,
        "clause": clause,
        "drift": None,
        "scope": spec["scope"],
        "notes": "",
    }

    if clause is None:
        resolved["notes"] = (
            f"{spec['source']} {spec['clause_no']}를 표준 조문 인덱스에서 찾지 못함 "
            f"— 원본 예규 파일과 인덱스를 확인하세요"
        )
        return resolved

    match = re.search(spec["anchor"], clause["text"])
    if not match:
        resolved["status"] = "anchor_failed"
        resolved["notes"] = (
            f"예규 원문에서 표준값 위치를 찾지 못함(문언 개정 의심) — {spec['note']}"
        )
        return resolved

    raw = match.group(1).strip()
    resolved["raw"] = raw

    # Wording rule: confirming the standard sentence is still present is enough.
    if spec["unit"] is None:
        resolved["status"] = "ok"
        resolved["desc"] = spec["desc_template"]
        return resolved

    candidates = [
        value
        for value in extract_values(raw)
        if value["unit"] == spec["unit"] and value.get("value") is not None
    ]
    if not candidates:
        resolved["status"] = "normalize_failed"
        resolved["notes"] = f"표준값 구간 '{raw}'을 {spec['unit']} 단위로 정규화하지 못함"
        return resolved

    value = candidates[0]["value"]
    resolved["status"] = "ok"
    resolved["value"] = value
    resolved["desc"] = spec["desc_template"].format(
        value=format_value(value, spec["unit"])
    )

    recorded = spec.get("recorded")
    if recorded is not None and abs(value - recorded) > 1e-4:
        resolved["drift"] = {"recorded": recorded, "extracted": value}
        resolved["notes"] = (
            f"예규 원문 값({format_value(value, spec['unit'])})이 코드에 기록된 값"
            f"({format_value(recorded, spec['unit'])})과 다릅니다 — 예규 개정으로 보입니다. "
            f"원문 값으로 판정했습니다. values.py의 recorded를 갱신하세요."
        )
    return resolved


def resolve_all(
    clauses: list[dict[str, Any]], *, contract_scope: str | None = None
) -> dict[str, dict[str, Any]]:
    """Resolve every rule's threshold at once, for one kind of contract."""
    return {
        rule_id: resolve_standard_value(rule_id, clauses, contract_scope=contract_scope)
        for rule_id in SPECS
    }
