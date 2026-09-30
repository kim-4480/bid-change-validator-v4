from bidengine.contracts import QualificationRequirement
from bidengine.diff.requirement_diff import diff_requirements, requirements_to_revalidate


def _req(key: str, *, req_type: str = "PERFORMANCE_AMOUNT", value=400_000_000, raw: str = "최근 3년 실적 4억원 이상"):
    return QualificationRequirement(
        requirement_key=key,
        requirement_group_key=f"{key}-GROUP",
        group_operator="ALL_OF",
        notice_version_id="version",
        type=req_type,
        operator=">=" if req_type == "PERFORMANCE_AMOUNT" else "MATCH",
        value=value,
        unit="KRW" if req_type == "PERFORMANCE_AMOUNT" else None,
        period_months=36 if req_type == "PERFORMANCE_AMOUNT" else None,
        scope={},
        raw=raw,
    )


def test_amount_threshold_change_is_modified():
    changes = diff_requirements([_req("REQ-001")], [_req("REQ-001", value=600_000_000, raw="최근 3년 실적 6억원 이상")])
    assert len(changes) == 1
    assert changes[0].change_type == "MODIFIED"
    assert requirements_to_revalidate(changes) == ["REQ-001"]


def test_shifted_extraction_key_can_still_be_unchanged():
    baseline = [_req("REQ-001")]
    current = [_req("REQ-004")]
    changes = diff_requirements(baseline, current)
    assert len(changes) == 1
    assert changes[0].change_type == "UNCHANGED"
    assert changes[0].baseline_key == "REQ-001"
    assert changes[0].current_key == "REQ-004"


def test_added_and_removed_are_separate_changes():
    baseline = [_req("REQ-REGION", req_type="REGION", value="서울특별시", raw="서울 소재")]
    current = [_req("REQ-CERT", req_type="REGISTRATION_CERTIFICATION", value="정보통신공사업", raw="정보통신공사업 등록")]
    changes = diff_requirements(baseline, current)
    assert {item.change_type for item in changes} == {"ADDED", "REMOVED"}


def test_changed_source_semantics_cannot_carry_user_answer():
    before = _req("REQ-1", raw="최근 3년 실적 4억원 이상")
    after = _req("REQ-1", raw="최근 3년 실적 4억원 이상, 공동수급 불가")
    assert diff_requirements([before], [after])[0].change_type == "MODIFIED"


def test_reordered_positional_keys_match_conditions_before_keys():
    a = _req("REQ-1", raw="구축 실적 4억원 이상")
    b = _req("REQ-2", raw="운영 실적 4억원 이상")
    changes = diff_requirements([a, b], [b.model_copy(update={"requirement_key": "REQ-1"}), a.model_copy(update={"requirement_key": "REQ-2"})])
    assert all(item.change_type == "UNCHANGED" for item in changes)
    assert {(item.baseline_key, item.current_key) for item in changes} == {("REQ-1", "REQ-2"), ("REQ-2", "REQ-1")}
