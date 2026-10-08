from datetime import date

from bidengine import extensions
from bidengine.contracts import QualificationRequirement
from bidengine.judgment.rules import CompanyProfileSnapshot, judge_requirement


NOTICE_VERSION_ID = "nv-001"
CASE_ID = "case-001"


def _requirement(raw: str, requirement_type: str = "STAFF") -> QualificationRequirement:
    return QualificationRequirement(
        requirement_key="REQ-0001-STAFF",
        notice_version_id=NOTICE_VERSION_ID,
        type=requirement_type,
        raw=raw,
        operator="MATCH",
    )


def test_a_notice_without_special_vocabulary_asks_for_nothing_extra() -> None:
    requirements = [_requirement("상시 인력 3인 이상 보유")]

    assert extensions.required_for(requirements) == []
    assert extensions.describe_required(requirements) == []


def test_engineer_grade_requirement_is_detected_and_owns_its_judgment() -> None:
    requirement = _requirement("특급기술자 2인 이상 참여")

    spec = extensions.spec_for_requirement(requirement)
    assert spec is not None
    assert spec.key == "sw_engineer_grade"
    assert [item["key"] for item in extensions.describe_required([requirement])] == [
        "sw_engineer_grade"
    ]


def test_engineer_grade_only_applies_to_staff_requirements() -> None:
    requirement = _requirement("특급기술자 2인 이상 참여", requirement_type="REGION")

    assert extensions.spec_for_requirement(requirement) is None


def test_affiliation_bundled_with_a_size_restriction_is_left_to_the_core_rule() -> None:
    requirement = _requirement(
        "대기업·중견기업 참여 제한, 상호출자제한기업집단 계열회사 참여 불가",
        requirement_type="COMPANY_SIZE",
    )

    # The core rule owns the judgment because it has to weigh company size too,
    # but the value still has to be collected from the user.
    assert extensions.spec_for_requirement(requirement) is None
    assert [spec.key for spec in extensions.required_for([requirement])] == [
        "conglomerate_affiliate"
    ]


def test_affiliation_alone_is_judged_by_the_extension() -> None:
    requirement = _requirement(
        "상호출자제한기업집단 계열회사는 참여할 수 없습니다", requirement_type="COMPANY_SIZE"
    )

    spec = extensions.spec_for_requirement(requirement)
    assert spec is not None
    assert spec.key == "conglomerate_affiliate"


def test_grade_answers_are_parsed_by_code_not_by_a_model() -> None:
    assert extensions.parse_answer_for("sw_engineer_grade", "특급 2명, 고급 3명") == {
        "특급": 2,
        "고급": 3,
    }
    assert extensions.parse_answer_for("sw_engineer_grade", "잘 모르겠습니다") is None
    assert extensions.parse_answer_for("unknown_key", "특급 2명") is None


def test_grade_answer_flows_into_the_qualification_judgment() -> None:
    requirement = _requirement("특급기술자 2인 이상 참여")
    profile = CompanyProfileSnapshot(
        company_id="company-1",
        extensions={"sw_engineer_grade": {"특급": 2}},
    )

    judgment = judge_requirement(
        requirement,
        profile,
        preflight_case_id=CASE_ID,
        reference_date=date(2026, 9, 9),
    )

    assert judgment.status == "SATISFIED"
    assert judgment.basis_type == "USER_ANSWER"
    assert judgment.profile_refs[0]["field"] == "sw_engineer_grade"


def test_grade_requirement_no_longer_uses_the_generic_staff_role_path() -> None:
    requirement = _requirement("특급기술자 2인 이상 참여")
    profile = CompanyProfileSnapshot.model_validate(
        {
            "company_id": "company-1",
            "staff": {
                "total_count": 10,
                "roles": [{"role_name": "특급", "headcount": 2}],
            },
            "completeness": {"staff_roles": True},
        }
    )

    judgment = judge_requirement(
        requirement,
        profile,
        preflight_case_id=CASE_ID,
        reference_date=date(2026, 9, 9),
    )

    assert judgment.status == "UNKNOWN"


def test_combined_size_and_affiliation_restriction_uses_the_extension_answer() -> None:
    requirement = _requirement(
        "대기업·중견기업 참여 제한, 상호출자제한기업집단 계열회사 참여 불가",
        requirement_type="COMPANY_SIZE",
    ).model_copy(
        update={"operator": "MATCH", "value": "대기업", "scope": {"restriction": "EXCLUDE"}}
    )

    def judged(answer):
        return judge_requirement(
            requirement,
            CompanyProfileSnapshot(
                company_id="company-1",
                company_size="SMALL",
                extensions={"conglomerate_affiliate": answer} if answer is not None else {},
            ),
            preflight_case_id=CASE_ID,
            reference_date=date(2026, 9, 9),
        )

    # 소기업으로 확인된 회사는 법상 상호출자제한기업집단 계열회사일 수 없다 — 묻지 않고 충족(2026-10-08).
    assert judged(None).status == "SATISFIED"
    assert judged({"is_affiliate": True}).status == "UNSATISFIED"
    assert judged({"is_affiliate": False}).status == "SATISFIED"


def test_yes_no_answers_read_negation_before_affirmation() -> None:
    parse = extensions.parse_answer_for
    assert parse("conglomerate_affiliate", "해당 없습니다") == {"is_affiliate": False}
    assert parse("conglomerate_affiliate", "네, 계열사입니다") == {"is_affiliate": True}
    assert parse("conglomerate_affiliate", "확인이 필요합니다") is None
    assert parse("conglomerate_affiliate", "") is None



def test_product_profile_path_cannot_answer_an_extension_yet() -> None:
    """제품 경로(Company → ProfileSnapshot)는 아직 `extensions` 를 채우지 않는다.

    이번 PR 범위는 "Core 판정 지원까지"다. 수집(ask_back)·저장(ORM)·적재
    (build_company_profile_snapshot) 세 자리가 비어 있어서, 제품에서 이 요건을
    만나면 결과는 항상 UNKNOWN 이다. 위 테스트들이 `extensions` 를 직접 넣어
    검증하는 것과 실제 제품 동작이 다르다는 사실을 여기서 고정해 둔다.

    연결이 끝나면 이 테스트가 깨진다 — 그것이 연결이 끝났다는 신호다.
    """
    from apps.api.app.models import Company
    from apps.api.app.qualification.judgment import build_company_profile_snapshot
    from bidengine.judgment.rules import ProfileCompleteness

    company = Company(name="테스트회사", company_size="SMALL")
    snapshot = build_company_profile_snapshot(company, ProfileCompleteness())

    assert snapshot.extensions == {}

    judgment = judge_requirement(
        _requirement("특급기술자 2인 이상 참여"),
        snapshot,
        preflight_case_id=CASE_ID,
        reference_date=date(2026, 9, 9),
    )

    assert judgment.status == "UNKNOWN"
