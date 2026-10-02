"""모델 분류가 흔들려도 원문의 숫자는 흔들리지 않는다.

[재현 2026-09-14] 구내식당 공고(R26BK01633750)를 여러 번 돌린 실측에서, 모델이
"영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자" 조항을 어떤
실행에서는 업종요건으로, 어떤 실행에서는 **기타요건**으로 분류했다. 기타요건은 통째로
버려졌다 — 골든셋은 이 조항을 INDUSTRY 1450 으로 본다.

분류는 작문이라 실행마다 달라진다. 업종코드 네 자리는 원문에 박혀 있어 달라지지 않는다.
그래서 분류가 '기타요건' 으로 와도 코드가 직접 읽어 살린다.

살리는 범위를 좁게 둔다. 숫자로 된 닫힌 식별자만 — 지역명·인증명처럼 사람이 달리 쓸 수
있는 값을 여기서 추측하기 시작하면 틀린 확정으로 간다.
"""

from __future__ import annotations

import pytest

from bidengine.requirements.legacy_slots import adapt_legacy_slot
from bidengine.requirements.legacy_slots import industry_code_alternation
from bidengine.requirements.legacy_slots import salvage_closed_identifier


def _adapt(raw: str, slot_type: str = "기타요건"):
    return adapt_legacy_slot(
        {"유형": slot_type, "raw": raw},
        notice_version_id="NV-1",
        key_prefix="REQ-001",
    )


def test_an_industry_code_survives_a_wrong_classification() -> None:
    raw = "식품위생법에 따른 인·허가를 득하고 영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자"

    requirements, diagnostics = _adapt(raw)

    assert [(item.type, item.value) for item in requirements] == [("INDUSTRY", "1450")]
    assert [item["code"] for item in diagnostics] == ["SALVAGED_CLOSED_IDENTIFIER"]
    # 원문은 그대로 달고 간다 — 판정 근거가 살린 값이 아니라 공고 문장이어야 한다.
    assert requirements[0].raw == raw


def test_a_product_code_survives_too() -> None:
    raw = "직접생산확인증명서[세부품명: 조형물(세부품명번호 10자리: 6012100201)] 보유 업체"

    requirements, _ = _adapt(raw)

    assert [(item.type, item.value) for item in requirements] == [
        ("REGISTRATION_CERTIFICATION", "6012100201")
    ]


def test_two_codes_are_not_salvaged() -> None:
    """둘 이상이면 AND 인지 OR 인지 모른다. 업종요건 경로가 멈추는 이유와 같다."""
    raw = "폐기물중간처분업(업종코드 : 1257) 또는 폐기물종합재활용업(업종코드 : 6786) 등록업체"

    requirements, diagnostics = _adapt(raw)

    assert requirements == []
    assert [item["code"] for item in diagnostics] == ["UNMAPPED_REQUIREMENT"]


@pytest.mark.parametrize(
    "raw",
    [
        "본점 소재지가 경상북도에 소재하고 있는 업체",          # 지역명은 추측하지 않는다
        "최근 3년 이내 유사 용역 실적 2건 이상 보유 업체",       # 숫자가 있어도 식별자가 아니다
        "입찰참가등록 및 입찰서 제출 정시에 마감합니다.",         # 요건이 아니다
        "사업자등록번호 1234567890 을 보유한 업체",             # 10자리지만 품명 맥락이 아니다
    ],
)
def test_prose_is_left_alone(raw: str) -> None:
    """넓히면 틀린 확정으로 간다. 살리는 것은 숫자로 된 닫힌 식별자뿐이다."""
    requirements, diagnostics = _adapt(raw)

    assert requirements == []
    assert [item["code"] for item in diagnostics] == ["UNMAPPED_REQUIREMENT"]


def test_an_unsafe_clause_is_still_not_salvaged() -> None:
    """안전 가드가 먼저다. 복합·예외 조항은 업종코드가 있어도 판정하지 않는다."""
    raw = (
        "건설폐기물수집·운반업(업종코드 : 6728)을 등록한 업체 또는 "
        "같은 법 시행규칙 제12조 제5항 [별표2] 장비기준을 충족한 업체"
    )

    requirements, diagnostics = _adapt(raw)

    assert requirements == []
    assert diagnostics[0]["code"] == "UNMAPPED_REQUIREMENT"
    assert diagnostics[0].get("reason")  # 가드 사유가 붙는다


def test_the_helper_reports_nothing_when_context_is_missing() -> None:
    """업종코드가 등록·신고 맥락 없이 나오면 살리지 않는다."""
    assert salvage_closed_identifier("업종코드 : 1450 참고") is None
    assert salvage_closed_identifier("영업신고(업종코드 : 1450)") == ("INDUSTRY", "1450")


def test_an_implausibly_small_amount_is_not_a_performance_requirement() -> None:
    """[재현 2026-09-15] 급식 실적 조항에서 정규화기가 0.0333원을 금액으로 냈다.
    "실적 금액 >= 0.03원" 은 무조건 충족이라 틀린 확정 방향이다. 판정에 넣지 않는다."""
    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "실적요건",
            "raw": "다. 입찰 공고일 기준 2년 내에 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적이 있는 업체",
            "금액_raw": "1일 평균 800식",
            "금액_norm": {"raw": "1일 평균 800식", "value": 0.0333, "unit": "KRW", "op": ">=", "parse_status": "success"},
        },
        notice_version_id="NV-1", key_prefix="R",
    )

    assert not any(item.type == "PERFORMANCE_AMOUNT" for item in requirements)
    assert any(d["code"] == "UNMAPPED_PERFORMANCE" and "하한" in d.get("reason", "") for d in diagnostics)


def test_a_normal_amount_still_maps() -> None:
    requirements, _ = adapt_legacy_slot(
        {
            "유형": "실적요건",
            "raw": "최근 3년 실적 5천만원 이상",
            "금액_raw": "5천만원 이상",
            "금액_norm": {"raw": "5천만원 이상", "value": 50000000, "unit": "KRW", "op": ">=", "parse_status": "success"},
        },
        notice_version_id="NV-1", key_prefix="R",
    )

    assert [(i.type, i.value) for i in requirements] == [("PERFORMANCE_AMOUNT", 50000000)]


def test_nara_market_registration_is_still_caught_when_the_model_splits_the_field() -> None:
    """[재현 2026-09-15, 검수 2차] 01634263-003 5회 중 1회, 모델이 "「국가종합전자조달시스템
    입찰참가자격등록규정」" 을 raw 가 아니라 등록인증_raw 에 담고 raw 에는 "입찰참가등록
    마감일시까지 입찰참가자격을 등록한 업체" 꼬리만 남겼다. 가드가 raw 만 보면 나라장터
    표시가 없는 문장이라 통과시켜 REGISTRATION_CERTIFICATION 유령을 만든다(실측 5회 중 1회
    재현). 어느 필드에 담겼든 절차는 절차다."""
    requirements, diagnostics = adapt_legacy_slot(
        {
            "유형": "등록요건",
            "raw": "입찰참가등록 마감일시까지 입찰참가자격을 등록한 업체",
            "등록인증_raw": "국가종합전자조달시스템 입찰참가자격등록규정",
        },
        notice_version_id="NV-1", key_prefix="R",
    )

    assert requirements == []
    assert [d["code"] for d in diagnostics] == ["UNMAPPED_REQUIREMENT"]
    assert diagnostics[0]["reason"] == "LEGAL_PROCEDURAL_RULE"


def test_a_condition_riding_along_with_one_alternative_is_not_silently_dropped() -> None:
    """[재현 2026-09-15, 코덱스 검수] "가공업(1257)을 등록하고 ISO 9001을 보유한 업체 또는
    운반업(1227)을 등록한 업체" 는 (1257 AND ISO 9001) OR 1227 인데, 조각마다 코드가
    "하나 있는지"만 보면 ["1257","1227"] 로 줄어 ISO 9001 조건이 조용히 사라진다.
    코드 문구를 뺀 나머지에 "보유"가 남아 있으니 ANY_OF 로 열지 않아야 한다."""
    raw = "가공업(1257)을 등록하고 ISO 9001을 보유한 업체 또는 운반업(1227)을 등록한 업체"

    assert industry_code_alternation(raw) is None

    requirements, diagnostics = adapt_legacy_slot(
        {"유형": "등록요건", "raw": raw},
        notice_version_id="NV-1", key_prefix="R",
    )

    # 코드 두 개로 조용히 줄지 않는다 — 관계를 모르니 안전하게 보류한다.
    assert requirements == []
    assert diagnostics[0]["reason"] == "ALTERNATIVE_OR_EXCEPTION_RULE"


def test_a_code_wrapped_inside_the_word_is_still_read_as_a_code() -> None:
    """[재현 2026-09-15, 골든 01688607] 원문이 "[업⏎종코드: 5898]" 로 낱말 안에서 줄을 바꾼다.
    raw 는 원문 구간으로 스냅되므로 그 줄바꿈이 그대로 들어오고, 코드 5898 대신 이름 값
    "제작자등(자동차-국내제작·조립[업종코드:5898])" 이 INDUSTRY 값으로 나왔다. 숫자는
    공백을 걷어내도 뜻이 안 바뀌니 걷어내고 읽는다."""
    raw = "1) ｢자동차관리법\n제30조에 의한 제작자 등(자동차-국내 제작·조립[업\n종코드: 5898])"

    requirements, _ = adapt_legacy_slot(
        {"유형": "업종요건", "raw": raw, "업종_raw": "자동차-국내 제작·조립[업\n종코드: 5898]"},
        notice_version_id="NV-1", key_prefix="R",
    )

    assert [(i.type, i.value) for i in requirements] == [("INDUSTRY", "5898")]


def test_a_plain_code_alternative_without_extra_conditions_still_opens() -> None:
    """추가 조건이 안 붙은 원래 모양은 그대로 ANY_OF 로 열려야 한다 — 위 가드가 정상
    사례까지 막으면 안 된다."""
    raw = "가공업(1257)을 등록한 업체 또는 운반업(1227)을 등록한 업체"

    assert industry_code_alternation(raw) == ["1257", "1227"]

    requirements, _ = adapt_legacy_slot(
        {"유형": "등록요건", "raw": raw},
        notice_version_id="NV-1", key_prefix="R",
    )

    assert {item.value for item in requirements} == {"1257", "1227"}
    assert {item.group_operator for item in requirements} == {"ANY_OF"}
