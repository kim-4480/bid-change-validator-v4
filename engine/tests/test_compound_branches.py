"""'(A 와 B) 또는 A' 같은 복합 조건을 갈래로 푼다(2026-10-10)."""
from datetime import date

from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, ProfileIndustryFact, judge_requirements
from bidengine.labeling.closed_first import (
    _closed_requirements, _combine_cross_branches, combine_branches, scan_candidates, written_code_branches,
)

ONE_CLAUSE = ("2) 「건설폐기물의 재활용촉진에 관한 법률」에 의한 건설폐기물 중간처분업[건설폐기물(업종코드:1253)]과 건설폐기물 수집·운반업"
              "[건설폐기물(업종코드:6728)] 또는 건설폐기물 중간처분업[건설폐기물(업종코드:1253)]을 등록한 업체 ※ 단, 장비기준을 충족한 "
              "경우에는 건설폐기물 수집·운반업으로 입찰참가 등록하지 않아도 입찰이 가능합니다.")


def _code(value, **extra):
    return {"type": "INDUSTRY", "value": value, "scope": {"industry_name": value}, **extra}


def _overall(items, codes):
    reqs = [QualificationRequirement(
        requirement_key=f"r{i}", requirement_group_key=item.get("group") or f"r{i}-G", group_operator="ANY_OF" if item.get("group") else "ALL_OF",
        notice_version_id="v", type="INDUSTRY", operator="MATCH", value=item["value"], raw="r", scope=item.get("scope") or {},
        requirement_role="preferred" if item.get("role") == "optional" else "mandatory",
    ) for i, item in enumerate(items)]
    profile = CompanyProfileSnapshot(
        company_id="c", region_name="전라남도 함평군", company_size="SMALL",
        industries=[ProfileIndustryFact(code=code, name=code, verified=True) for code in codes],
        completeness={"region": True, "company_size": True, "industries": True},
    )
    return judge_requirements(reqs, profile, preflight_case_id="c", reference_date=date(2026, 10, 10), coverage_complete=True).overall_status


def test_a_code_in_every_branch_is_required_and_the_rest_is_optional():
    out = combine_branches([[_code("1253"), _code("6728")], [_code("1253")]])
    assert [(r["value"], r.get("role")) for r in out] == [("1253", None), ("6728", "optional")]
    assert _overall(out, ["1253"]) == "core_met"
    assert _overall(out, ["6728"]) == "core_unmet"


def test_branches_with_several_codes_are_alternatives_as_wholes():
    out = combine_branches([[_code("0002")], [_code("4989"), _code("4991")]])
    assert _overall(out, ["0002"]) == "core_met"
    assert _overall(out, ["4989", "4991"]) == "core_met"
    assert _overall(out, ["4991"]) == "needs_review"       # 갈래 구조는 코드가 읽은 것 — 부적합으로 확정하지 않는다
    out = combine_branches([[_code("1001"), _code("1002")], [_code("1001"), _code("1003")]])
    assert [r["value"] for r in out if not r.get("group")] == ["1001"]
    assert _overall(out, ["1001", "1003"]) == "core_met" and _overall(out, ["1002", "1003"]) == "core_unmet"


def test_one_clause_is_split_on_or():
    candidates = scan_candidates(ONE_CLAUSE, None)
    branches = written_code_branches(ONE_CLAUSE, candidates)
    assert [[c.value for c in branch] for branch in branches] == [["1253", "6728"], ["1253"]]
    plain = "전기공사업(업종코드:0037) 또는 정보통신공사업(업종코드:0036)을 등록한 업체"
    assert written_code_branches(plain, scan_candidates(plain, None)) is None      # 평범한 대안은 모델이 정한 대로


def test_the_model_calling_the_clause_an_exception_does_not_lose_the_required_code():
    candidates = scan_candidates(ONE_CLAUSE, None)
    for polarity in ("POSITIVE", "EXCEPTION"):
        reqs, _diags = _closed_requirements(polarity, ONE_CLAUSE, candidates, {})
        assert [(r["value"], r.get("role")) for r in reqs if r["type"] == "INDUSTRY"] == [("1253", None), ("6728", "optional")]
    reqs, _diags = _closed_requirements("EXCLUSION", ONE_CLAUSE, candidates, {})
    assert reqs == []


def test_sub_items_with_several_codes_and_a_relaxing_note():
    # 748965: ① 1389·1254·1229  ② 1254·1229  ※ 장비 기준을 충족하면 1254 또는 1389 와 1254 로 가능
    slots = [None, {"raw": "①", "_closed_requirements": [_code("1389"), _code("1254"), _code("1229")]},
             {"raw": "②", "_closed_requirements": [_code("1254"), _code("1229")]}]
    note = ("※ 장비 기준을 충족한 경우에는, 폐기물중간처분업(지정폐기물)[1254] 또는 폐기물최종처분업(지정폐기물)[1389]과 "
            "폐기물중간처분업(지정폐기물)[1254]으로 입찰이 가능합니다.")
    without = _combine_cross_branches(slots, [])
    assert [(r["value"], r.get("role")) for r in without] == [("1229", None), ("1254", None), ("1389", "optional")]
    with_note = _combine_cross_branches(slots, [note])
    assert [(r["value"], r.get("role")) for r in with_note] == [("1254", None), ("1229", "optional"), ("1389", "optional")]
    assert _overall(with_note, ["1254"]) == "core_met"
    # 대안 묶음이 이미 있거나 추론한 코드가 섞인 갈래는 풀지 않는다.
    grouped = [None, {"raw": "①", "_closed_requirements": [_code("1001"), {**_code("1002"), "group": "G"}]}, slots[2]]
    assert _combine_cross_branches(grouped, []) is None


def test_sme_priority_exception_is_not_a_size_requirement():
    from bidengine.requirements.legacy_slots import has_closed_value_text

    assert not has_closed_value_text("제2조의3(중소기업자와의 우선조달계약에 대한 예외)에 따라 중소기업자 우선조달계약에 대한 예외가 적용되는 용역입니다.")
    assert not has_closed_value_text("본 용역은 중소기업자 우선조달계약에 대한 예외사유에 해당합니다.")
    assert has_closed_value_text("본 용역은 중소기업자 우선조달계약 대상입니다.")
    assert not has_closed_value_text("「중소기업제품 공공구매제도 운영요령」제44조에 따라 중소기업자 우선조달계약에 대한 예외가 적용되는 용역입니다.")
