"""추출 재현율 대조기가 너무 느슨하지도, 너무 엄격하지도 않은지 고정한다.

너무 엄격하면 검증기가 버린 것과 같은 이유로 놓쳐서 측정이 "전부 MISSED" 가 되고,
너무 느슨하면 아무거나 맞아서 재현율이 부풀어 "문제 없음" 이 된다. 둘 다 측정을
쓸모없게 만드는데, 방향이 반대라 한쪽만 조심하면 다른 쪽으로 넘어간다.
"""

from bideval.extraction_recall import (
    GoldenRequirement,
    normalize,
    place_requirements,
    same_requirement,
    unmapped_raws_from_diagnostics,
)


TRANSPORT = GoldenRequirement(
    key="transport", type="INDUSTRY",
    raw="건설폐기물수집·운반업 (업종코드 : 6728)을 등록한 업체 또는 같은 법 시행규칙 제12조 제5항 [별표2] 1. 가. 수집·운반업 허가기준의 장비기준을 충족한 업체",
)
REGION = GoldenRequirement(
    key="region", type="REGION", value="전남광주통합특별시",
    raw="본점소재지를 전남광주통합특별시에 소재한 업체",
)


def test_special_dots_and_spacing_do_not_break_the_match() -> None:
    """실제 탈락 사례 — 모델은 '수집·운반업', 원문은 '수집․운반업'. 같은 요건이다."""
    model_quote = "다. 「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 건설폐기물수집·운반업 (업종코드 : 6728)을 등록한 업체"
    source_variant = "건설폐기물수집․운반업(업종코드:6728)을 등록한 업체"

    assert normalize(model_quote) != normalize(TRANSPORT.raw)  # 통째로는 다르다
    assert same_requirement(TRANSPORT, model_quote)              # 그래도 같은 요건
    assert same_requirement(TRANSPORT, source_variant)


def test_a_shared_industry_code_is_enough() -> None:
    """원문이 아예 다르게 요약됐어도 업종코드 6728 이 같으면 같은 요건이다."""
    assert same_requirement(TRANSPORT, "폐기물 수집운반업 등록(6728)")


def test_a_short_common_fragment_is_not_a_match() -> None:
    """'등록한 업체' 같은 토막은 어느 요건에나 있다. 이것으로 맞추면 재현율이 부푼다."""
    assert not same_requirement(TRANSPORT, "등록한 업체")
    assert not same_requirement(REGION, "소재한 업체")


def test_same_type_and_value_match_even_when_wording_differs() -> None:
    assert same_requirement(REGION, "본사가 전남광주통합특별시 안에 있을 것", "REGION", "전남광주통합특별시")
    # 값이 같아도 유형이 다르면 다른 요건이다.
    assert not same_requirement(REGION, "전남광주통합특별시", "INDUSTRY", "전남광주통합특별시")


def test_each_golden_requirement_lands_in_exactly_one_bucket() -> None:
    """R26BK01634263 에서 실제로 벌어진 모양: 하나는 버려지고, 둘은 어디에도 없다."""
    processing = GoldenRequirement("processing", "INDUSTRY", "건설폐기물중간처리업 (업종코드 : 1253)을 등록한 업체", "1253")
    recall = place_requirements(
        "01634263-003",
        [processing, TRANSPORT, REGION],
        extracted=[{"raw": "입찰참가자격등록규정에 따라 입찰참가자격을 등록한 업체", "type": "REGISTRATION_CERTIFICATION"}],
        dropped=[{"raw": "건설폐기물수집·운반업 (업종코드 : 6728)을 등록한 업체 또는", "reason_code": "RAW_NOT_FOUND_IN_SOURCE"}],
        unmapped_raws=["3. 견적서 제출자격 ‣ 단독이행"],
    )

    outcomes = {p.key: (p.outcome, p.reason_code) for p in recall.placements}
    assert outcomes == {
        "processing": ("MISSED", None),
        "transport": ("DROPPED", "RAW_NOT_FOUND_IN_SOURCE"),
        "region": ("MISSED", None),
    }
    # 골든셋에 없는 추출물은 따로 센다 — 이것도 신호다.
    assert recall.extras == ["입찰참가자격등록규정에 따라 입찰참가자격을 등록한 업체"]


def test_reached_wins_over_dropped_when_both_hold_the_same_requirement() -> None:
    """재시도로 같은 요건이 두 곳에 있으면 가장 멀리 간 것으로 센다."""
    recall = place_requirements(
        "x", [TRANSPORT],
        extracted=[{"raw": "건설폐기물수집·운반업(6728) 등록", "type": "INDUSTRY"}],
        dropped=[{"raw": "건설폐기물수집·운반업(6728) 등록", "reason_code": "RAW_NOT_FOUND_IN_SOURCE"}],
        unmapped_raws=[],
    )

    assert recall.placements[0].outcome == "REACHED"


def test_only_unmapped_diagnostics_are_read_as_notice_facts() -> None:
    raws = unmapped_raws_from_diagnostics([
        {"code": "EXTRACTION_PARTIAL", "kind": "PIPELINE", "details": {"notes": "x"}},
        {"code": "UNMAPPED_REQUIREMENT", "kind": "NOTICE_FACT", "details": {"raw": "단독이행"}},
        {"code": "UNMAPPED_REQUIREMENT", "kind": "NOTICE_FACT", "details": {}},
    ])

    assert raws == ["단독이행"]
