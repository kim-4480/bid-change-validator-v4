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


def _alt(key, value, raw="건설엔지니어링업(종합) 또는 건설엔지니어링업(설계·사업관리-일반)로 등록한 자"):
    return QualificationRequirement(
        requirement_key=key, requirement_group_key="G", group_operator="ANY_OF", notice_version_id="v",
        type="INDUSTRY", operator="MATCH", value=value, scope={"guard": "assessed"}, raw=raw,
    )


def test_alternatives_in_one_clause_are_unchanged_even_when_keys_shift():
    """한 조항의 대안 묶음 — 같은 자리 요건이 여럿이다. 추출 순서 키가 바뀌어도 변경 없음이다."""
    baseline = [_alt("R-001-ALT-1", "4966"), _alt("R-001-ALT-2", "4967")]
    current = [_alt("R-003-ALT-1", "4967"), _alt("R-003-ALT-2", "4966")]
    changes = diff_requirements(baseline, current)
    assert [c.change_type for c in changes] == ["UNCHANGED", "UNCHANGED"]


def test_one_alternative_replaced_in_same_clause_is_modified():
    baseline = [_alt("A1", "4966"), _alt("A2", "4967")]
    current = [_alt("B1", "4966"), _alt("B2", "4969")]
    kinds = sorted(c.change_type for c in diff_requirements(baseline, current))
    assert kinds == ["MODIFIED", "UNCHANGED"]


def test_renumbered_item_is_unchanged():
    """G2 실측: 앞 항목(강원도 본점)이 빠져 "4) …1169" 가 "3) …1169" 가 됐다. 번호는 내용이 아니다."""
    clause = " 「국가종합전자조달시스템 입찰참가자격등록규정」에 의하여 학술·연구용역(업종코드:1169)으로 등록한 자"
    before = _alt("A", "1169", raw="4)" + clause)
    after = _alt("B", "1169", raw="3)" + clause)
    assert [c.change_type for c in diff_requirements([before], [after])] == ["UNCHANGED"]


def test_descriptive_industry_name_span_does_not_make_a_change():
    clause = "4) 학술·연구용역(업종코드:1169)으로 경쟁입찰 참가자격을 등록한 자"
    before = _alt("A", "1169", raw=clause).model_copy(update={"scope": {"industry_name": "학술·연구용역(업종코드:1169)", "guard": "assessed"}})
    after = _alt("B", "1169", raw=clause).model_copy(update={"scope": {"industry_name": "학술·연구용역(업종코드:1169)으로 경쟁입찰 참가자격을 등록한 자", "guard": "assessed"}})
    assert [c.change_type for c in diff_requirements([before], [after])] == ["UNCHANGED"]


def test_same_documents_never_report_a_change():
    """문서가 같은 두 차수(일정·공고번호만 바뀐 변경공고)는 분석 결과가 달라도 변경이 아니다."""
    from bidengine.diff.requirement_diff import diff_same_documents, documents_fingerprint

    baseline = [_req("A", req_type="INDUSTRY", value="1468", raw="업종코드 1468 등록"),
                _req("B", req_type="INDUSTRY", value="9901", raw="업종코드 9901 등록")]
    current = [_req("A", req_type="INDUSTRY", value="1468", raw="업종코드 1468 등록"),
               _req("C", req_type="INDUSTRY", value="0037", raw="전기공사업 등록")]
    changes = diff_same_documents(baseline, current)
    assert {c.change_type for c in changes} == {"UNCHANGED"}
    assert {c.current_key for c in changes} == {"A", "C"}
    assert documents_fingerprint(["a", "b"]) == documents_fingerprint(["a", "b"])
    assert documents_fingerprint(["a", None]) is None


def _assessed(key, value, raw, req_type="INDUSTRY"):
    return _req(key, req_type=req_type, value=value, raw=raw).model_copy(update={"scope": {"guard": "assessed"}})


def test_assessed_requirement_with_same_value_is_unchanged_when_only_the_clause_text_changes():
    """한 조항의 지역만 바꿨다 — 같은 조항의 업종은 값이 그대로라 변경이 아니다(가상 변경 시험)."""
    before = [_assessed("REQ-001-C01", "0037", "전기공사업 등록 업체로서 제주특별자치도내에 본점")]
    after = [_assessed("REQ-001-C01", "0037", "전기공사업 등록 업체로서 서울특별시내에 본점")]
    assert [c.change_type for c in diff_requirements(before, after)] == ["UNCHANGED"]
    # 가드 평가를 거치지 않은 요건은 판정이 원문을 다시 읽으므로 원문이 바뀌면 여전히 수정이다
    plain = diff_requirements([_req("A", req_type="INDUSTRY", value="0037", raw="가. 0037 업체")],
                              [_req("A", req_type="INDUSTRY", value="0037", raw="가. 0037 업체 또는 0036 업체")])
    assert [c.change_type for c in plain] == ["MODIFIED"]


def test_same_requirement_is_matched_even_when_its_clause_was_rewritten():
    """앞에 조건이 끼어 조항 원문과 순번이 바뀌어도, 판정 내용이 같은 요건은 '삭제 + 추가' 가 아니다."""
    before = [_assessed("REQ-005-C01", "6010640201", "마. 논리회로실험장치(세부품명번호 6010640201)로 등록한 자", "REGISTRATION_CERTIFICATION")]
    after = [_assessed("REQ-005-C01", "서울특별시", "마. 본점 소재지가 서울특별시에 있는 업체", "REGION"),
             _assessed("REQ-006-C01", "6010640201", "마. 본점 소재지가 서울특별시에 있는 업체이어야 합니다. 바. 논리회로실험장치(세부품명번호 6010640201)로 등록한 자", "REGISTRATION_CERTIFICATION")]
    kinds = sorted((c.change_type, (c.current or c.baseline).type) for c in diff_requirements(before, after))
    assert kinds == [("ADDED", "REGION"), ("UNCHANGED", "REGISTRATION_CERTIFICATION")]
