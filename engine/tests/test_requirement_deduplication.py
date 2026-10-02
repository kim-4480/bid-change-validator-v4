"""같은 조항이 두 유형으로 분류됐을 때 자격 있는 회사를 떨어뜨리지 않는지.

[재현 2026-09-14] 모델의 유형 분류는 실행마다 흔들린다. 구내식당 공고의 한 조항이
어떤 실행에서는 INDUSTRY, 어떤 실행에서는 REGISTRATION_CERTIFICATION, 어떤 실행에서는
**둘 다** 로 나왔다. 둘 다 나온 실행이 위험하다 — ALL_OF 묶음이라 둘 다 충족해야 하는데,
업종 1450 을 실제로 보유한 회사가 인증 쪽에서 미달을 받는다.

여기서 고정하는 것은 두 가지다. 접어야 할 것을 접는가, 그리고 **접으면 안 되는 것을
그대로 두는가.** 뒤엣것이 더 중요하다 — 잘못 접으면 진짜 요건이 사라지고, 그건 조용히
지나간다. 첫 구현에서 실제로 ISO 9001 을 삼켰다.
"""

from __future__ import annotations

from datetime import date

import pytest

from bidengine.contracts import QualificationRequirement
from bidengine.requirements.deduplicate import deduplicate_requirements
from bidengine.judgment.rules import CompanyProfileSnapshot
from bidengine.judgment.rules import judge_requirement
from bidengine.judgment.rules import judge_requirements


LONG_RAW = (
    "나. 식품위생법에 의거 단체급식업 등록업체로서 결격사유가 없는 업체 "
    "식품위생법에 따른 인·허가를 득하고 영업신고(업종코드 : 1450)를 한 업체"
)
SHORT_RAW = "나. 식품위생법에 의거 단체급식업 등록업체로서 결격사유가 없는 업체"


def _requirement(key: str, type_: str, value: str, raw: str) -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key=key,
        notice_version_id="NV-1",
        type=type_,
        operator="MATCH",
        value=value,
        raw=raw,
        requirement_group_key="G",
        group_operator="ALL_OF",
    )


def test_the_same_fact_classified_twice_is_folded_onto_the_industry_code() -> None:
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", "단체급식업등록", SHORT_RAW),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert [(item.type, item.value) for item in kept] == [("INDUSTRY", "1450")]
    assert [item["code"] for item in diagnostics] == ["MERGED_INDUSTRY_REGISTRATION"]
    # 무엇이 접혔는지 남는다 — 담당자가 확인할 수 있어야 한다.
    assert diagnostics[0]["dropped_value"] == "단체급식업등록"
    assert diagnostics[0]["kept_value"] == "1450"


def test_folding_prevents_a_wrong_unsatisfied() -> None:
    """이 정리가 무엇을 막는지 판정까지 내려가서 확인한다."""
    profile = CompanyProfileSnapshot.model_validate({
        "company_id": "C-1",
        "industries": [{"code": "1450", "name": "단체급식업", "verified": False}],
        "certifications": [],
        "completeness": {
            "certifications": True, "company_size": True, "industries": True,
            "performances": True, "region": True, "staff_roles": True, "staff_total": True,
        },
    })
    registration = _requirement(
        "A", "REGISTRATION_CERTIFICATION", "단체급식업등록", SHORT_RAW
    )

    # 정리 전에는 업종을 보유한 회사가 인증 쪽에서 미달을 받았다.
    before = judge_requirement(
        registration, profile, preflight_case_id="X", reference_date=date(2026, 9, 14)
    )
    assert before.status == "UNSATISFIED"

    kept, _ = deduplicate_requirements([
        registration, _requirement("B", "INDUSTRY", "1450", LONG_RAW)
    ])
    statuses = {
        judge_requirement(
            item, profile, preflight_case_id="X", reference_date=date(2026, 9, 14)
        ).status
        for item in kept
    }

    assert statuses == {"SATISFIED"}


def test_exact_duplicates_collapse_to_one() -> None:
    """실측 run 에서 같은 INDUSTRY 1450 이 세 번 들어왔다. 개수가 부풀어 보인다."""
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "INDUSTRY", "1450", LONG_RAW),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
        _requirement("C", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert len(kept) == 1
    assert [item["code"] for item in diagnostics] == [
        "DUPLICATE_REQUIREMENT", "DUPLICATE_REQUIREMENT"
    ]


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("ISO 9001", "규격 이름은 업종명이 아니다 — 별개 인증 요건"),
        ("직접생산확인증명서", "업종명이 아니다"),
        ("KS Q 27001", "로마자·숫자가 섞이면 규격 이름"),
    ],
)
def test_a_real_certification_requirement_is_never_folded(value: str, why: str) -> None:
    raw = f"업종(1257) 등록 및 {value} 보유 업체"
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", value, raw),
        _requirement("B", "INDUSTRY", "1257", raw),
    ])

    assert len(kept) == 2, why
    assert diagnostics == []


def test_two_different_requirements_in_one_clause_are_left_alone() -> None:
    """한 조항이 지역과 업종을 정말로 둘 다 요구할 수 있다. 접으면 판정이 사라진다."""
    raw = "소재지가 전북특별자치도이고 업종(1257)을 등록한 업체"
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "REGION", "전북특별자치도", raw),
        _requirement("B", "INDUSTRY", "1257", raw),
    ])

    assert len(kept) == 2
    assert diagnostics == []


def test_nothing_is_folded_onto_an_industry_without_a_code() -> None:
    """접는 근거는 '코드가 더 확실하다' 이다. 코드가 없으면 근거가 없다."""
    kept, _ = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", "단체급식업등록", SHORT_RAW),
        _requirement("B", "INDUSTRY", "단체급식업", LONG_RAW),
    ])

    assert len(kept) == 2


def test_an_unrelated_clause_is_not_folded_even_with_a_matching_name() -> None:
    """원문이 겹치지 않으면 같은 조항이 아니다."""
    kept, _ = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", "단체급식업등록", "다. 별개 조항의 단체급식업등록 요구"),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert len(kept) == 2


def test_a_certification_slot_with_one_industry_code_becomes_industry() -> None:
    """[재현 2026-09-15] 같은 "영업신고(업종코드 : 1450)" 조항을 모델이 인증요건으로 낸
    실행이 있었다. 그때 INDUSTRY 1450 이 안 만들어져 인증 쪽에서 미달이 났다.
    분류가 뭐라 하든 업종코드가 하나면 업종 요건이다."""
    from bidengine.requirements.legacy_slots import adapt_legacy_slot

    for slot_type in ("인증요건", "면허요건", "등록요건"):
        requirements, _ = adapt_legacy_slot(
            {"유형": slot_type, "raw": LONG_RAW, "등록인증_raw": "영업신고"},
            notice_version_id="NV-1", key_prefix="R",
        )
        assert [(item.type, item.value) for item in requirements] == [("INDUSTRY", "1450")], slot_type


def test_the_run_that_produced_only_two_registrations_collapses_to_one_industry() -> None:
    """luna run2 그대로 — INDUSTRY 없이 등록 둘. 하나는 코드가 있어 INDUSTRY 가 되고,
    나머지 하나는 그 위로 접혀야 한다."""
    from bidengine.requirements.canonicalize import canonicalize_validated_slots

    blocks = [{"document_id": "doc", "block_index": 0, "page": 1, "location": "p.1"}]
    result = canonicalize_validated_slots([
        {"유형": "등록요건", "raw": SHORT_RAW, "등록인증_raw": "단체급식업 등록업체",
         "_source_blocks": blocks, "_source_chunk_id": "C1"},
        {"유형": "인증요건", "raw": LONG_RAW, "등록인증_raw": "영업신고",
         "_source_blocks": blocks, "_source_chunk_id": "C1"},
    ], notice_version_id="NV-1")

    assert [(item.type, item.value) for item in result["requirements"]] == [("INDUSTRY", "1450")]


@pytest.mark.parametrize("value", ["단체급식업등록업체", "영업신고", "단체급식업"])
def test_registration_act_phrases_count_as_industry_names(value: str) -> None:
    kept, _ = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", value, SHORT_RAW),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert [(item.type, item.value) for item in kept] == [("INDUSTRY", "1450")]


# ---- 2026-09-15 두 번째 실측에서 나온 유령 셋 ----


def test_a_name_valued_industry_folds_onto_the_coded_one() -> None:
    """run0: 같은 조항에서 INDUSTRY "단체급식업" 과 INDUSTRY "1450" 이 둘 다 나왔다."""
    kept, diagnostics = deduplicate_requirements([
        _requirement("A", "INDUSTRY", "단체급식업", SHORT_RAW),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert [(item.type, item.value) for item in kept] == [("INDUSTRY", "1450")]
    assert diagnostics[0]["code"] == "MERGED_INDUSTRY_REGISTRATION"


@pytest.mark.parametrize("act", ["인·허가", "인허가", "영업신고", "허가", "등록"])
def test_a_bare_registration_act_folds_onto_the_industry_code(act: str) -> None:
    """run1: "인·허가" 처럼 등록 행위 낱말만 값으로 낸 인증 요건. 인증 이름이 아니다."""
    kept, _ = deduplicate_requirements([
        _requirement("A", "REGISTRATION_CERTIFICATION", act, LONG_RAW),
        _requirement("B", "INDUSTRY", "1450", LONG_RAW),
    ])

    assert [(item.type, item.value) for item in kept] == [("INDUSTRY", "1450")]


def test_the_same_requirement_read_from_two_documents_is_one() -> None:
    """run2: 공고문과 제안요청서에 같은 조항이 두 벌. 원문만 다르고 나머지는 같다."""
    def req(key: str, raw: str) -> QualificationRequirement:
        return QualificationRequirement(
            requirement_key=key, notice_version_id="NV-1", type="EXPERIENCE_FIELD",
            operator="MATCH", value="단체급식소 운영", raw=raw,
            requirement_group_key="G", group_operator="ALL_OF",
            scope={"experience_field": "단체급식소 운영"},
        )

    kept, diagnostics = deduplicate_requirements([
        req("A", "다. 2개 이상 각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영"),
        req("B", "다. 2개 이상 각 단체급식소*(1일 평균 800식 이상)를 1년간 운영"),
    ])

    assert len(kept) == 1
    assert [item["code"] for item in diagnostics] == ["DUPLICATE_REQUIREMENT"]


def test_same_value_but_different_scope_stays_separate() -> None:
    """금액이 같아도 경험분야가 다르면 별개 요건이다. 원문을 열쇠에서 뺀 대가로 범위는 넣는다."""
    def req(key: str, field: str) -> QualificationRequirement:
        return QualificationRequirement(
            requirement_key=key, notice_version_id="NV-1", type="PERFORMANCE_AMOUNT",
            operator=">=", value=50000000, raw=f"{field} 실적 5천만원 이상",
            requirement_group_key="G", group_operator="ALL_OF",
            scope={"experience_field": field}, period_months=36,
        )

    kept, _ = deduplicate_requirements([req("A", "IoT 플랫폼"), req("B", "AI 학습")])

    assert len(kept) == 2


def test_a_coded_industry_never_folds_onto_another() -> None:
    """코드끼리는 접지 않는다. 1257 과 6770 은 다른 업종이다 — ANY_OF 묶음의 구성원들이다."""
    kept, _ = deduplicate_requirements([
        _requirement("A", "INDUSTRY", "1257", LONG_RAW),
        _requirement("B", "INDUSTRY", "6770", LONG_RAW),
    ])

    assert len(kept) == 2


def test_a_real_certification_in_a_coded_clause_is_not_turned_into_industry() -> None:
    """기존 test_canonicalize 가 막는 경우를 여기서도 고정한다. 코드가 있다고 값을 업종으로
    바꾸면 같은 조항의 ISO 27001 을 삼킨다. 값 모양이 업종명·등록행위일 때만 바꾼다."""
    from bidengine.requirements.legacy_slots import adapt_legacy_slot

    kept_cert, _ = adapt_legacy_slot(
        {"유형": "인증요건", "raw": "업종코드: 1468 업체는 ISO 27001 인증 보유", "등록인증_raw": "ISO 27001"},
        notice_version_id="NV-1", key_prefix="R",
    )
    assert [(i.type, i.value) for i in kept_cert] == [("REGISTRATION_CERTIFICATION", "ISO 27001")]

    turned, _ = adapt_legacy_slot(
        {"유형": "인증요건", "raw": LONG_RAW, "등록인증_raw": "영업신고"},
        notice_version_id="NV-1", key_prefix="R",
    )
    assert [(i.type, i.value) for i in turned] == [("INDUSTRY", "1450")]


def test_a_decoration_mark_does_not_split_one_requirement_into_two() -> None:
    """[재현 2026-09-15] 공고문은 ※ 로, 제안요청서는 * 로 같은 조항을 적었다. 값이 한 글자
    달라 완전 중복으로 안 잡혔고 경험분야 요건이 둘로 나왔다."""
    def req(key: str, mark: str) -> QualificationRequirement:
        value = f"2개 이상 각 단체급식소{mark}(1일 평균 800식 이상)를 1년 이상 운영"
        return QualificationRequirement(
            requirement_key=key, notice_version_id="NV-1", type="EXPERIENCE_FIELD",
            operator="MATCH", value=value, raw=value,
            requirement_group_key="G", group_operator="ALL_OF",
            scope={"experience_field": value},
        )

    kept, diagnostics = deduplicate_requirements([req("A", "※"), req("B", "*")])

    assert len(kept) == 1
    assert [item["code"] for item in diagnostics] == ["DUPLICATE_REQUIREMENT"]


def test_split_sentences_of_one_clause_fold_when_they_share_a_chunk() -> None:
    """[재현 2026-09-15] 모델이 "나." 조항의 앞 문장(단체급식업 등록업체)과 뒷 문장
    (영업신고(업종코드 : 1450))을 따로 인용했다. 두 원문이 서로를 안 담는다. 같은 청크에서
    나왔다는 사실로 같은 조항임을 안다."""
    from bidengine.requirements.canonicalize import canonicalize_validated_slots

    blocks = [{"document_id": "doc", "block_index": 0, "page": 1, "location": "p.1"}]
    first = "나. 식품위생법에 의거 단체급식업 등록업체로서 식당허가 등에 결격사유가 없는 업체"
    second = "식품위생법에 따른 인·허가를 득하고 동법 시행령에 따라 영업신고(업종코드 : 1450)를 하여 집단급식소 영업이 가능한 법인사업자"
    result = canonicalize_validated_slots([
        {"유형": "업종요건", "raw": first, "업종_raw": "단체급식업",
         "_source_blocks": blocks, "_source_chunk_id": "CHUNK-0007"},
        {"유형": "인증요건", "raw": second, "등록인증_raw": "인·허가",
         "_source_blocks": blocks, "_source_chunk_id": "CHUNK-0007"},
        {"유형": "업종요건", "raw": second, "업종_raw": "집단급식소",
         "_source_blocks": blocks, "_source_chunk_id": "CHUNK-0007"},
    ], notice_version_id="NV-1")

    assert [(i.type, i.value) for i in result["requirements"]] == [("INDUSTRY", "1450")]


def test_named_industries_in_different_chunks_are_not_folded() -> None:
    """청크가 다르면 다른 조항이다. "가. 컴퓨터관련서비스사업" 과 "나. …(업종코드 1468)" 은
    별개 요건이고, 앞엣것을 뒤엣것으로 접으면 요건 하나가 사라진다."""
    from bidengine.requirements.canonicalize import canonicalize_validated_slots

    blocks = [{"document_id": "doc", "block_index": 0, "page": 1, "location": "p.1"}]
    result = canonicalize_validated_slots([
        {"유형": "업종요건", "raw": "가. 컴퓨터관련서비스사업", "업종_raw": "컴퓨터관련서비스사업",
         "_source_blocks": blocks, "_source_chunk_id": "CHUNK-0010"},
        {"유형": "업종요건", "raw": "나. 디지털콘텐츠개발서비스사업(업종코드 : 1468)", "업종_raw": "디지털콘텐츠개발서비스사업",
         "_source_blocks": blocks, "_source_chunk_id": "CHUNK-0011"},
    ], notice_version_id="NV-1")

    assert len(result["requirements"]) == 2


def test_any_of_members_are_not_collapsed_as_exact_duplicates() -> None:
    """[재현 2026-09-15, 코덱스 검수] "(A 또는 B) 그리고 (A 또는 C)" 에서 두 묶음에 같은
    값 A 가 있으면, 완전중복 규칙이 뒤에 나온 A 를 지워 조건이 (A 또는 B) 그리고 C 로
    바뀐다 — A만 가진 회사가 충족→미달로 뒤집힌다. ANY_OF 묶음 소속은 완전중복 정리
    대상에서 뺀다."""
    def any_of(key: str, group: str, value: str) -> QualificationRequirement:
        return QualificationRequirement(
            requirement_key=key, notice_version_id="NV-1", type="INDUSTRY",
            operator="MATCH", value=value, raw=f"{value} 등록업체",
            requirement_group_key=group, group_operator="ANY_OF",
        )

    requirements = [
        any_of("G1-A", "G1", "1257"), any_of("G1-B", "G1", "6770"),
        any_of("G2-A", "G2", "1257"), any_of("G2-C", "G2", "1227"),
    ]

    kept, diagnostics = deduplicate_requirements(requirements)

    # 넷 다 남는다 — 값이 같아도 서로 다른 묶음 소속이면 지우지 않는다.
    assert len(kept) == 4
    assert not any(d["code"] == "DUPLICATE_REQUIREMENT" for d in diagnostics)

    # 판정까지 내려가서 확인한다. 1257 만 가진 회사는 두 묶음 다 충족해야 한다.
    profile = CompanyProfileSnapshot.model_validate({
        "company_id": "C-1",
        "industries": [{"code": "1257", "name": "가공업", "verified": False}],
        "certifications": [],
        "completeness": {
            "certifications": True, "company_size": True, "industries": True,
            "performances": True, "region": True, "staff_roles": True, "staff_total": True,
        },
    })
    result = judge_requirements(
        kept, profile, preflight_case_id="X", reference_date=date(2026, 9, 15)
    )

    assert result.overall_status == "eligible"
