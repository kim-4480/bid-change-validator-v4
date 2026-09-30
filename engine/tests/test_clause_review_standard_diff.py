from typing import Any

import pytest

from bidengine.clause_review import detect_standard_diff as _review
from bidengine.clause_review.standards import resolve_all, split_clauses


def detect_standard_diff(chunks, clauses, **kwargs) -> list[Any]:
    """Review the fixture below as a 소프트웨어용역 contract.

    하자보수(제58조), 하자보수보증금(제59조) and 지식재산권(제56조) are stated in the
    소프트웨어용역 chapter, so they only apply to that kind of contract. The one-line
    chunks here carry no words for the scope to be read from, so the tests say
    which chapter they mean instead of leaving it to be guessed.
    """
    kwargs.setdefault("contract_scope", "SOFTWARE")
    return _review(chunks, clauses, **kwargs)


# A trimmed stand-in for 용역계약일반조건. Every threshold the rules compare against
# is read out of this text, so the tests exercise the real extraction path rather
# than constants written into the test.
STANDARD_TEXT = """제2장 계약의 이행

제18조(지체상금)
①계약담당공무원은 계약상대자가 계약의 이행을 지체한 때에는 지체상금을 부과하여야 한다. 다만, 지체상금의 총액이 계약금액의 100분의 30을 초과하는 경우에는 100분의 30으로 한다.

제20조(검사)
②계약담당공무원은 제1항의 통지를 받은 날부터 14일 이내에 그 검사를 완료하여야 한다.

제31조(계약의 해제·해지)
①계약상대자는 다음 각 호의 어느 하나에 해당하는 경우 계약을 해제 또는 해지할 수 있다.
1. 계약금액이 100분의 40이상 감소되었을 때

제35조의2(계약목적물의 지식재산권 귀속 등)
①해당 계약에 따른 계약목적물에 대한 지식재산권은 발주기관과 계약상대자가 공동으로 소유한다
②지식재산권과 관련한 기타사항은 제56조를 준용한다.

제23조(일반적 손해)
①계약상대자는 계약의 수행 중 용역목적물 및 제3자에 대한 손해를 부담하여야 한다. 다만, 그 손해가 계약상대자의 책임없는 사유로 인하여 발생한 경우에는 발주기관의 부담으로 한다.

제27조(대가의 지급)
②계약담당공무원은 제1항의 청구를 받은 때에는 그 청구를 받은 날로부터 5일(공휴일 및 토요일은 제외한다) 이내에 그 대가를 지급하여야 한다.

제4장 계약의 종료

제56조(지식재산권의 귀속)
①이 계약에 의하여 작성된 산출물에 대한 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며, 특약이 없으면 지분은 균등한 것으로 한다.

제58조(하자보수)
①계약상대자는 사업의 종료를 확인한 후 1년간 발생한 하자에 대하여 보수책임이 있다.

제59조(하자보수보증금)
①계약상대자는 하자보수보증금율(100분의 2, 장기계속계약의 경우에는 연차별로 산정한다)에 해당하는 금액을 납부하여야 한다.
"""


# 지체상금 requires two documents: 용역계약일반조건 caps the total, while the per-day
# rate is set by 시행규칙 제75조 (제55조 only points at it).
ENFORCEMENT_RULE_TEXT = """제75조(지체상금률)
영 제74조제1항에 따른 지체상금률은 다음 각호와 같다.
1. 공사: 1천분의 0.5
3. 물품의 수리ㆍ가공ㆍ대여,용역(소프트웨어사업시 일괄 입찰의 그 용역을 제외한다) 및 기타: 1천분의 1.25
5. 운송ㆍ보관 및 양곡가공: 1천분의 2.5
"""


@pytest.fixture(scope="module")
def clauses() -> list[dict]:
    return split_clauses("용역계약일반조건", STANDARD_TEXT) + split_clauses(
        "국가계약법 시행규칙", ENFORCEMENT_RULE_TEXT
    )


def _chunk(text: str, chunk_id: str = "CHUNK-0001", clause_label: str | None = "5.1") -> dict:
    return {"chunk_id": chunk_id, "clause_label": clause_label, "text": text}


def _by_rule(findings) -> dict:
    return {finding.rule_id: finding for finding in findings}


# ── the thresholds come from the rule text, not from code ────────────────
def test_every_threshold_is_read_out_of_the_standard_text(clauses) -> None:
    resolved = resolve_all(clauses)

    assert {rule_id: item["status"] for rule_id, item in resolved.items()} == {
        "warranty_period": "ok",
        "warranty_bond_rate": "ok",
        "penalty_rate": "ok",
        "penalty_cap": "ok",
        "inspection_period": "ok",
        "termination_threshold": "ok",
        "payment_period": "ok",
        "ip_ownership": "ok",
        "liability_scope": "ok",
    }
    assert resolved["penalty_rate"]["value"] == 0.125
    assert resolved["penalty_rate"]["raw"] == "1천분의 1.25"
    assert resolved["warranty_period"]["value"] == 12
    assert resolved["warranty_period"]["raw"] == "1년"
    assert resolved["penalty_cap"]["value"] == 30
    assert resolved["warranty_bond_rate"]["value"] == 2
    assert resolved["termination_threshold"]["value"] == 40
    # No drift: the extracted values match what the specs recorded.
    assert all(item["drift"] is None for item in resolved.values())


def test_an_amended_threshold_is_used_and_flagged_as_drift() -> None:
    amended = split_clauses(
        "용역계약일반조건",
        "제58조(하자보수)\n①계약상대자는 사업의 종료를 확인한 후 2년간 발생한 하자에 대하여 보수책임이 있다.\n",
    )
    resolved = resolve_all(amended)["warranty_period"]

    # The rule text wins; the mismatch with the recorded value is reported.
    assert resolved["value"] == 24
    assert resolved["drift"] == {"recorded": 12, "extracted": 24}
    assert "개정" in resolved["notes"]

    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 인수 확인 후 18개월간 하자보수 책임을 진다.")], amended
        )
    )
    # 18 months is over the standard 12 but within an amended 24.
    assert findings["warranty_period"].verdict == "COMPLIANT"


def test_a_missing_standard_clause_withholds_the_verdict(clauses) -> None:
    without_warranty = [item for item in clauses if item["clause_no"] != "58조"]

    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 하자담보책임기간은 인수일로부터 36개월로 한다.")], without_warranty
        )
    )

    finding = findings["warranty_period"]
    assert finding.verdict == "UNDETERMINED"
    assert finding.matched_via == "STANDARD_UNRESOLVED"
    assert "판정 보류" in finding.reason


# ── numeric comparison ───────────────────────────────────────────────────
def test_a_warranty_period_over_the_standard_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 인수 확인 후 36개월간 하자보수 책임을 진다.")], clauses
        )
    )

    finding = findings["warranty_period"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.notice_value == 36
    assert finding.standard is not None
    assert finding.standard.value == 12
    assert finding.standard.clause_ref == "용역계약일반조건 제58조제1항"
    # The excerpt of the standard clause travels with the finding as its ground.
    assert finding.standard.text_excerpt


def test_a_warranty_period_within_the_standard_is_compliant(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 인수 확인 후 12개월간 하자보수 책임을 진다.")], clauses
        )
    )

    assert findings["warranty_period"].verdict == "COMPLIANT"


def test_a_penalty_cap_over_the_standard_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("6.1 지체상금의 총액은 계약금액의 100분의 50을 한도로 한다.")], clauses
        )
    )

    finding = findings["penalty_cap"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.notice_value == 50


def test_the_daily_penalty_rate_is_not_compared_against_the_cap(clauses) -> None:
    # 0.5% is the per-day rate, not a cap. Comparing it would report every notice
    # as compliant on a number that has nothing to do with the standard.
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "6.1 지체상금은 지연일수 1일당 계약금액의 0.5%로 하며, "
                    "그 총액은 계약금액의 100분의 30을 초과하지 아니한다."
                )
            ],
            clauses,
        )
    )

    finding = findings["penalty_cap"]
    assert finding.verdict == "COMPLIANT"
    assert finding.notice_value == 30


# ── 지체상금: 상한과 요율은 서로 다른 값이다 ─────────────────────────────
# A notice states both in one breath — "1일당 0.5%로 하며, 총액은 100분의 30을
# 초과하지 아니한다" — and the two figures come from different documents, so each
# rule has to take its own and leave the other alone.
def test_the_cap_and_the_rate_are_judged_separately_in_one_sentence(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "6.1 지체상금은 지연일수 1일당 계약금액의 0.5%로 하며, "
                    "그 총액은 계약금액의 100분의 30을 초과하지 아니한다."
                )
            ],
            clauses,
        )
    )

    # The ceiling matches 제18조제1항.
    assert findings["penalty_cap"].verdict == "COMPLIANT"
    assert findings["penalty_cap"].notice_value == 30
    # 0.5% a day is four times 시행규칙 제75조제3호.
    rate = findings["penalty_rate"]
    assert rate.verdict == "NEEDS_REVIEW"
    assert rate.notice_value == 0.5
    assert rate.standard is not None
    assert rate.standard.value == 0.125
    assert rate.standard.clause_ref == "국가계약법 시행규칙 제75조제3호"


def test_the_standard_daily_rate_is_compliant(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("6.1 지체상금률은 계약금액의 1천분의 1.25로 한다.")], clauses
        )
    )

    assert findings["penalty_rate"].verdict == "COMPLIANT"
    assert findings["penalty_rate"].notice_value == 0.125


def test_a_daily_rate_over_the_standard_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("6.1 지체상금은 지연일수 1일당 계약금액의 1천분의 3으로 한다.")], clauses
        )
    )

    assert findings["penalty_rate"].verdict == "NEEDS_REVIEW"
    assert findings["penalty_rate"].notice_value == 0.3
    # No ceiling was stated, so the cap rule has nothing to compare and says so.
    assert findings["penalty_cap"].verdict == "UNDETERMINED"


def test_a_construction_fraction_rate_is_normalized(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("제22조 지체상금은 계약금액을 기준으로 지체1일당 1/1,000로 산정한다.")],
            clauses,
            contract_scope="CONSTRUCTION",
        )
    )

    finding = findings["penalty_rate"]
    assert finding.notice_value == 0.1
    assert finding.notice_value_raw.startswith("1/1,000")
    assert finding.verdict == "NEEDS_REVIEW"


def test_a_stricter_termination_threshold_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("8.1 계약금액이 100분의 60 이상 감소한 경우에 한하여 계약을 해지할 수 있다.")],
            clauses,
        )
    )

    assert findings["termination_threshold"].verdict == "NEEDS_REVIEW"
    assert findings["termination_threshold"].notice_value == 60


# ── figures must not be attributed to the wrong rule ─────────────────────
def test_a_warranty_figure_is_not_read_as_an_inspection_period(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 하자담보책임기간은 검수완료일로부터 36개월로 한다.")], clauses
        )
    )

    # The warranty rule owns this sentence.
    assert findings["warranty_period"].verdict == "NEEDS_REVIEW"
    assert findings["warranty_period"].notice_value == 36
    # The inspection rule must not claim the same 36 months. The sentence is
    # excluded from it entirely, so it reports nothing rather than a wrong value.
    assert "inspection_period" not in findings


def test_a_bond_rate_figure_is_not_read_as_a_warranty_period(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.2 하자보수보증금은 계약금액의 100분의 10으로 한다.")], clauses
        )
    )

    assert findings["warranty_bond_rate"].verdict == "NEEDS_REVIEW"
    assert findings["warranty_bond_rate"].notice_value == 10
    # The warranty-period rule excludes any sentence mentioning a bond, so the
    # 100분의 10 here can never be read as a warranty duration.
    assert "warranty_period" not in findings


# ── wording comparison ───────────────────────────────────────────────────
def test_sole_vesting_of_intellectual_property_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("9.1 본 용역의 모든 산출물에 대한 저작권은 발주기관에 귀속한다.")], clauses
        )
    )

    finding = findings["ip_ownership"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.matched_text


def test_joint_ownership_wording_matches_the_standard(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "9.1 산출물의 지식재산권은 발주기관과 계약상대자가 공동으로 소유하며 "
                    "지분은 균등한 것으로 한다."
                )
            ],
            clauses,
        )
    )

    assert findings["ip_ownership"].verdict == "COMPLIANT"


def test_a_sole_vesting_sentence_is_still_found_next_to_a_compliant_one(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "9.1 산출물의 지식재산권은 양 당사자가 공동으로 소유한다.\n"
                    "9.2 다만 소프트웨어 저작재산권은 발주기관이 단독 보유한다."
                )
            ],
            clauses,
        )
    )

    # Checking the chunk as a whole would let the compliant sentence hide this.
    assert findings["ip_ownership"].verdict == "NEEDS_REVIEW"


# ── the embedding tier only runs when tier one gave no answer ────────────
def _recording_fallback(verdict=None):
    calls: list[str] = []

    def fallback(rule, resolved, chunks, inspected_ids):
        calls.append(rule["id"])
        if verdict is None:
            return (None, "", None, None, None)
        return (verdict, "임베딩 검색으로 근거 확인", None, "인용문", chunks[0])

    fallback.calls = calls  # type: ignore[attr-defined]
    return fallback


def test_a_confident_regex_verdict_does_not_trigger_the_embedding_tier(clauses) -> None:
    fallback = _recording_fallback()

    detect_standard_diff(
        [_chunk("5.1 계약상대자는 인수 확인 후 36개월간 하자보수 책임을 진다.")],
        clauses,
        embedding_fallback=fallback,
    )

    assert "warranty_period" not in fallback.calls


def test_a_rule_with_no_regex_match_does_trigger_the_embedding_tier(clauses) -> None:
    fallback = _recording_fallback(verdict="NEEDS_REVIEW")

    findings = _by_rule(
        detect_standard_diff(
            [_chunk("5.1 계약상대자는 품질을 보장하며 발생하는 문제를 자비로 해결한다.")],
            clauses,
            embedding_fallback=fallback,
        )
    )

    assert "warranty_period" in fallback.calls
    assert findings["warranty_period"].matched_via == "EMBEDDING_LLM"


def test_without_a_fallback_an_unmatched_rule_simply_reports_nothing(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("3.1 시스템 분석 및 설계를 수행한다.")], clauses
        )
    )

    assert "warranty_period" not in findings


def test_findings_carry_the_notice_version(clauses) -> None:
    findings = detect_standard_diff(
        [_chunk("5.1 인수 확인 후 36개월간 하자보수 책임을 진다.")],
        clauses,
        notice_version_id="nv-001",
    )

    assert all(finding.notice_version_id == "nv-001" for finding in findings)


# ── 대금지급 (제27조제2항) ───────────────────────────────────────────────
def test_a_payment_deadline_beyond_the_standard_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("7.1 발주기관은 대가지급 청구를 받은 날부터 30일 이내에 대가를 지급한다.")],
            clauses,
        )
    )

    finding = findings["payment_period"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.standard is not None
    assert finding.standard.clause_ref == "용역계약일반조건 제27조제2항"
    assert finding.standard.value_raw == "5일"


def test_a_payment_deadline_within_the_standard_is_compliant(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("7.1 발주기관은 대가지급 청구를 받은 날부터 5일 이내에 대가를 지급한다.")],
            clauses,
        )
    )

    assert findings["payment_period"].verdict == "COMPLIANT"


def test_payment_reference_without_a_deadline_stays_undetermined(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "발주기관은 용역계약일반조건 및 계약서 등에 따라 검사를 통하여 "
                    "대가를 지급한다."
                )
            ],
            clauses,
        )
    )

    assert findings["payment_period"].verdict == "UNDETERMINED"
    assert findings["payment_period"].notice_value is None


def test_a_liquidated_damages_figure_is_not_read_as_a_payment_deadline(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("6.1 지체상금은 지연일수 1일당 계약금액의 0.5%로 하며 총액은 100분의 30을 초과하지 아니한다.")],
            clauses,
        )
    )

    assert "payment_period" not in findings


# ── 손해배상 (제23조제1항) ───────────────────────────────────────────────
# The standard does not cap what may be claimed; it draws a line at fault. So a
# notice departs from it by erasing that line, not by naming a larger figure.
def test_liability_without_regard_to_fault_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("8.1 계약상대자는 귀책사유를 불문하고 본 용역과 관련한 일체의 손해를 배상하여야 한다.")],
            clauses,
        )
    )

    finding = findings["liability_scope"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.standard is not None
    assert finding.standard.clause_ref == "용역계약일반조건 제23조제1항"
    assert finding.matched_text


def test_unlimited_liability_wording_is_flagged(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("8.2 계약상대자는 본 계약과 관련하여 발생하는 모든 손해에 대하여 무한 책임을 진다.")],
            clauses,
        )
    )

    assert findings["liability_scope"].verdict == "NEEDS_REVIEW"


def test_the_fault_carve_out_is_recognised_in_a_proviso_of_its_own(clauses) -> None:
    """The 다만 sentence need not name the harm again, so it is not one of the
    rule's own sentences. It still has to count as the standard wording."""
    findings = _by_rule(
        detect_standard_diff(
            [
                _chunk(
                    "8.1 계약상대자는 용역목적물의 손해를 부담한다. "
                    "다만 계약상대자의 책임없는 사유로 발생한 경우에는 발주기관이 부담한다."
                )
            ],
            clauses,
        )
    )

    assert findings["liability_scope"].verdict == "COMPLIANT"


def test_deferring_to_the_standard_terms_counts_as_compliant(clauses) -> None:
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("8.1 손해의 부담에 관하여는 용역계약일반조건에 따른다.")], clauses
        )
    )

    assert findings["liability_scope"].verdict == "COMPLIANT"


# ── which chapter of the rules governs ───────────────────────────────────
# 용역계약일반조건 is chaptered, and a chapter decides which contracts a clause
# binds. Measuring a 물품 notice against the 소프트웨어용역 chapter reports a breach
# of a standard that never applied to it.
def test_a_software_only_standard_is_not_applied_to_another_kind_of_contract(
    clauses,
) -> None:
    chunk = _chunk("5.1 계약상대자는 인수 확인 후 36개월간 하자보수 책임을 진다.")

    software = _by_rule(detect_standard_diff([chunk], clauses, contract_scope="SOFTWARE"))
    common = _by_rule(detect_standard_diff([chunk], clauses, contract_scope="COMMON"))

    # 36 months exceeds the 소프트웨어용역 standard of 1년 (제58조).
    assert software["warranty_period"].verdict == "NEEDS_REVIEW"
    # For any other 용역 the rules set no warranty period, so there is nothing to
    # measure against and the rule stays out of the review entirely.
    assert "warranty_period" not in common
    assert "warranty_bond_rate" not in common


def test_the_common_chapter_has_its_own_intellectual_property_standard(clauses) -> None:
    """제35조의2 is the 공통 counterpart of 제56조, added in 2014.

    It states joint ownership but leaves the share split to 제56조, so a review
    outside 소프트웨어용역 is measured against ownership alone.
    """
    findings = _by_rule(
        detect_standard_diff(
            [_chunk("9.1 본 용역의 모든 산출물에 대한 저작권은 발주기관에 귀속한다.")],
            clauses,
            contract_scope="COMMON",
        )
    )

    finding = findings["ip_ownership"]
    assert finding.verdict == "NEEDS_REVIEW"
    assert finding.standard is not None
    assert finding.standard.clause_ref == "용역계약일반조건 제35조의2제1항"


def test_the_scope_is_read_off_the_notice_when_it_is_not_given() -> None:
    from bidengine.clause_review import infer_contract_scope

    software = [
        _chunk("1.1 본 사업은 통합정보시스템 구축을 위한 소프트웨어 개발 용역이다."),
        _chunk("1.2 소프트웨어 산출물은 검수 후 인계한다."),
    ]
    assert infer_contract_scope(software) == "SOFTWARE"

    construction_management = [
        _chunk("1.1 시공 단계의 건설사업관리 용역이다."),
        _chunk("1.2 건설사업관리기술인을 배치한다. 건설사업관리 대가는 별도로 정한다."),
    ]
    assert infer_contract_scope(construction_management) == "CM"

    # A single passing mention must not switch the standard, and an unmarked
    # notice falls back to the chapter that governs every 용역 contract.
    assert infer_contract_scope([_chunk("1.1 청사 사무용 가구 구매 건이다.")]) == "COMMON"
    assert (
        infer_contract_scope([_chunk("1.1 사무용 가구를 정보시스템에 등록한다.")]) == "COMMON"
    )
