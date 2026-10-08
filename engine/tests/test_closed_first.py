"""닫힌 값 먼저(closed_first): 코드가 후보를 찾고, 모델은 역할만 정하고, 코드가 요건을 만든다."""
from __future__ import annotations

from bidengine.labeling.closed_first import SCHEMA, scan_candidates, unresolved_industry_names
from bidengine.pipeline.analysis_pipeline import (
    QualificationAnalysisInput,
    QualificationDocumentInput,
    analyze_qualification_documents,
)
from bidengine.pipeline.analysis_result import clause_accounting

SECTION = """3. 입찰참가자격
가. 관광진흥법에 의한 종합여행업(업종코드 1 2 6 1) 또는 국내외여행업(업종코드 1262)으로 등록한 업체
나. 본점 소재지가 전주시인 업체이어야 합니다. 납품장소: 서울특별시 중구
다. 중기업·소기업 또는 소상공인으로서 확인서를 소지한 업체
라. 대기업 및 중견기업은 참여할 수 없습니다.
마. 최근 3년 이내 단일 계약 1억원 이상의 행사 대행 실적이 있는 업체
4. 입찰보증금"""


class Resolver:
    def code_for(self, name):
        return None


def test_candidates_are_found_by_code():
    found = {(c.kind, c.value) for c in scan_candidates(SECTION, Resolver())}
    assert ("INDUSTRY", "1261") in found and ("INDUSTRY", "1262") in found
    assert ("REGION", "전주시") in found and ("REGION", "서울특별시 중구") in found
    assert {("SIZE", "중기업"), ("SIZE", "소기업"), ("SIZE", "소상공인"), ("SIZE", "대기업")} <= found


def fake_model(system, body, schema):
    if schema is not SCHEMA:
        return {"clauses": []}  # 조항 선택 호출(code 선택이면 부르지 않는다)
    answers = []
    for block in body.split("\n\n"):
        head = block.split("\n", 1)[0]
        cid = head[1:5]
        ids = {part.split()[0]: part for part in head.split("후보: ", 1)[1].split("; ")} if "후보: V" in head else {}
        text = block.split("\n", 1)[1]
        roles, polarity, open_reqs = [], "NOT_REQUIREMENT", []
        if "여행업" in text:
            polarity = "POSITIVE"
            roles = [{"id": i, "role": "ALTERNATIVE", "group": "G1"} for i in ids]
        elif "전주시" in text:
            polarity = "POSITIVE"
            roles = [{"id": i, "role": "REQUIRED" if "전주시" in p else "NOT_RELATED", "group": ""} for i, p in ids.items()]
        elif "소상공인" in text:
            polarity = "POSITIVE"
            roles = [{"id": i, "role": "ALTERNATIVE", "group": "G1"} for i in ids]
        elif "대기업" in text:
            polarity = "EXCLUSION"
            roles = [{"id": i, "role": "EXCLUDED", "group": ""} for i in ids]
        elif "실적" in text:
            polarity = "POSITIVE"
            open_reqs = [{name: None for name in SCHEMA["schema"]["properties"]["clauses"]["items"]["properties"]["open_requirements"]["items"]["required"]}
                         | {"유형": "실적요건", "기간_raw": "최근 3년 이내", "금액_raw": "1억원 이상", "경험분야_raw": "행사 대행"}]
        answers.append({"clause_id": cid, "polarity": polarity, "candidates": roles, "open_requirements": open_reqs})
    return {"clauses": answers}


def _analyze(memory=None):
    return analyze_qualification_documents(
        QualificationAnalysisInput(notice_id="n", notice_version_id="v", documents=[
            QualificationDocumentInput(document_id="d", extracted_blocks=[{"block_index": 0, "text": SECTION}])]),
        structured_extract=fake_model, extraction_mode="closed_first", clause_selection="code",
        industry_resolver=Resolver(), labeling_memory=memory, memory_namespace="fake",
    )


def test_roles_become_requirements_without_retyping():
    result = _analyze()
    got = {(r.type, str(r.value), r.group_operator, r.scope.get("restriction")) for r in result.requirements}
    assert ("INDUSTRY", "1261", "ANY_OF", None) in got and ("INDUSTRY", "1262", "ANY_OF", None) in got
    assert ("REGION", "전주시", "ALL_OF", None) in got
    assert not any(t == "REGION" and "중구" in v for t, v, _g, _r in got)  # 납품 장소는 요건이 아니다
    assert ("COMPANY_SIZE", "중소기업", "ALL_OF", None) in got            # 중기업∪소기업∪소상공인
    assert ("COMPANY_SIZE", "대기업 및 중견기업", "ALL_OF", "EXCLUDE") in got
    assert any(r.type == "PERFORMANCE_AMOUNT" for r in result.requirements)


def test_every_clause_has_a_visible_outcome_and_answers_are_remembered():
    memory: dict = {}
    result = _analyze(memory)
    from bidengine.labeling.clause_labeling import select_clauses
    from bidengine.pipeline.analysis_pipeline import _build_global_chunks

    chunks = _build_global_chunks([QualificationDocumentInput(document_id="d", extracted_blocks=[{"block_index": 0, "text": SECTION}])], max_chunk_chars=1800)
    kept, *_ = select_clauses(chunks, structured_extract=fake_model)
    assert clause_accounting([c.text for c in kept], result) == []
    assert memory  # 답을 기억했다
    again = _analyze(memory)
    assert [(r.type, r.value) for r in again.requirements] == [(r.type, r.value) for r in result.requirements]


def test_noisy_open_names_are_dropped():
    from bidengine.labeling.closed_first import Candidate, open_name_is_noise

    product = [Candidate(id="V1", kind="PRODUCT", value="4918169801", surface="4918169801")]
    assert open_name_is_noise("제14조에 의한 자격요건", "", []) == "STATUTE_OR_PROCEDURE"
    assert open_name_is_noise("이용자등록", "", []) == "GENERIC_NAME"
    assert open_name_is_noise("구매 및 제조물품", "", []) == "STATUTE_OR_PROCEDURE"
    assert open_name_is_noise("사격총", "", product) == "PRODUCT_NAME_DUPLICATE"
    assert open_name_is_noise("ISO 9001 인증", "", product) is None      # 번호가 있는 진짜 인증
    assert open_name_is_noise("건설기계조종사면허", "", []) is None


def test_first_answer_is_the_majority_of_several_samples():
    """같은 질문을 세 번 보내 다수 답을 쓴다 — 세 번 중 한 번만 다른 답은 버려진다."""
    from bidengine.labeling.closed_first import extract_closed_first
    from bidengine.pipeline.analysis_pipeline import _build_global_chunks

    chunks = _build_global_chunks([QualificationDocumentInput(document_id="d", extracted_blocks=[{"block_index": 0, "text": SECTION}])], max_chunk_chars=1800)
    calls = {"n": 0}

    def flaky(system, body, schema):
        calls["n"] += 1
        answer = fake_model(system, body, schema)
        if calls["n"] == 2:  # 두 번째 답만 지역 조항을 '요건 아님' 으로 낸다
            for entry in answer["clauses"]:
                if any(c["role"] == "REQUIRED" for c in entry["candidates"]):
                    entry["polarity"] = "NOT_REQUIREMENT"
        return answer

    out = extract_closed_first(chunks, structured_extract=flaky, industry_resolver=Resolver(), clause_selection="code", votes=3)
    assert calls["n"] == 3
    regions = [r for s in out["slots"] for r in s.get("_closed_requirements", []) if r["type"] == "REGION"]
    assert [r["value"] for r in regions] == ["전주시"]


def _clause(cid, text):
    from bidengine.clauses.enumerate import Clause
    return Clause(clause_id=cid, chunk_id="K0", text=text, source_blocks=())


def _closed_slot(text, reqs):
    return {"유형": "_CLOSED", "raw": text, "_closed_requirements": reqs, "_closed_diagnostics": []}


def test_cross_clause_alternative_with_a_multi_item_branch_is_left_for_review():
    """'어느 하나' 아래 ㉯ 가 업종 셋을 모두 요구하면 '(㉮) 또는 (㉯ 전부)' 를 담을 수 없다 — 확인 필요로 둔다."""
    from bidengine.labeling.closed_first import _merge_cross_clause_alternatives

    head = "2) 업종 중 다음 각 호 어느 하나에 해당하는 경우 ㉮ 종합공사업: 건축공사업(또는 토목건축공사업)을 등록한 자"
    sub = "㉯ 전문공사업: 지반조성·포장공사업과 금속창호·지붕건축물조립공사업과 도장·습식·방수·석공사업을 등록한 자"
    slots = [_closed_slot(head, [{"type": "INDUSTRY", "value": "0002", "group": "G1"}, {"type": "INDUSTRY", "value": "0003", "group": "G1"}]),
             _closed_slot(sub, [{"type": "INDUSTRY", "value": v} for v in ("4989", "4991", "4992")])]
    _merge_cross_clause_alternatives([_clause("C001", head), _clause("C002", sub)], slots)
    assert all(s["_closed_requirements"] == [] for s in slots)
    assert {d["reason"] for s in slots for d in s["_closed_diagnostics"]} == {"CROSS_CLAUSE_ALTERNATIVE"}


def test_cross_clause_alternative_with_single_item_branches_becomes_one_any_of_group():
    from bidengine.labeling.closed_first import _merge_cross_clause_alternatives

    head = "가. 다음 중 하나에 해당하는 업체 ㉮ 종합여행업(업종코드 1261)을 등록한 자"
    sub = "㉯ 국내외여행업(업종코드 1262)을 등록한 자"
    slots = [_closed_slot(head, [{"type": "INDUSTRY", "value": "1261"}]), _closed_slot(sub, [{"type": "INDUSTRY", "value": "1262"}])]
    _merge_cross_clause_alternatives([_clause("C001", head), _clause("C002", sub)], slots)
    groups = {r["group"] for s in slots for r in s["_closed_requirements"]}
    assert len(groups) == 1 and None not in groups


def test_bracket_industry_codes_and_duplicate_names():
    from bidengine.labeling.closed_first import scan_candidates

    text = "① 폐기물중간처분업(지정폐기물)[1254]과 폐기물수집·운반업(지정폐기물)[1229]의 허가를 득한 자"
    found = {(c.kind, c.value) for c in scan_candidates(text, Resolver())}
    assert {("INDUSTRY", "1254"), ("INDUSTRY", "1229")} <= found


def test_statute_names_are_not_registration_names():
    from bidengine.labeling.closed_first import open_name_is_noise

    assert open_name_is_noise("건설산업기본법", "", []) == "STATUTE_OR_PROCEDURE"
    assert open_name_is_noise("「전기공사업법」", "", []) == "STATUTE_OR_PROCEDURE"
    assert open_name_is_noise("건설기계조종사면허", "", []) is None


def test_size_written_as_competition_type_is_a_requirement():
    """'○○간 경쟁입찰로 진행' 은 절차 안내처럼 보여도 참가 업체의 규모를 정한다 — 모델이 요건 아님으로 읽어도 담는다."""
    from bidengine.labeling.closed_first import _closed_requirements, scan_candidates

    for text, expected in [
        ("나. 판로지원법 시행령 제2조의2 제1항 1호에 의거 소기업 또는 소상공인간 경쟁입찰로 진행합니다.", "소기업"),
        ("다. 본 입찰은 소기업 또는 소상공인 간 제한경쟁입찰입니다.", "소기업"),
        ("나. 중소기업자간 경쟁입찰로 진행합니다.", "중소기업"),
    ]:
        reqs, _ = _closed_requirements("NOT_REQUIREMENT", text, scan_candidates(text, Resolver()), {})
        assert reqs == [{"type": "COMPANY_SIZE", "value": expected, "scope": {"source": "competition_type"}}], text
    # 경쟁 방식 문장이 아니면 예전대로 모델의 극성을 따른다
    reqs, diags = _closed_requirements("NOT_REQUIREMENT", "소기업 확인서는 마감일까지 제출합니다.", [], {})
    assert reqs == [] and diags


class MasterResolver:
    NAMES = {"산림사업법인(숲가꾸기및병해충방제)": "1475", "전문소방시설공사업": "0040",
             "일반소방시설공사업(전기)": "0039", "일반소방시설공사업(기계)": "0038"}

    def code_for(self, name):
        return self.NAMES.get("".join(name.split()))


def test_scanner_reads_codes_after_saeopja_and_qualified_names():
    """2026-10-07 표본 h: '…사업자(1468)', 괄호 세부명이 붙은 이름, 닫는 괄호가 빠진 세부명 나열."""
    scan = lambda text: {(c.kind, c.value) for c in scan_candidates(text, MasterResolver())}
    assert ("INDUSTRY", "1468") in scan("- 소프트웨어사업자(1468) 업종을 등록한 업체")
    assert ("INDUSTRY", "1475") in scan("법률에 의한「산림사업법인(숲가꾸기 및 병해충방제)」또는 「산림조합」")
    assert {("INDUSTRY", "0040"), ("INDUSTRY", "0039"), ("INDUSTRY", "0038")} <= scan(
        "소방시설공사업법령에 의한【전문소방시설공사업】또는【일반소방시설공사업(전기, 기계】면허를 보유한 업체")
    assert not any(kind == "INDUSTRY" for kind, _v in scan("체육관 증축공사(2026) 설계 실적이 있는 업체"))


def test_alternative_with_an_unresolved_name_does_not_become_a_required_industry():
    """(나) '1475 또는 산림조합' 에서 1475 만 필수로 만들면 산림조합은 '불가' 가 된다 — 확인 필요로 둔다."""
    from bidengine.labeling.closed_first import _check_closed_values

    text = "가. 「산림사업법인(숲가꾸기 및 병해충방제)」또는 산림조합법에 의하여 설립된「산림조합」으로 본점소재지가 곡성군"
    candidates = scan_candidates(text, MasterResolver())
    reqs = [{"type": "REGION", "value": "곡성군", "scope": {}}, {"type": "INDUSTRY", "value": "1475", "scope": {}}]
    reqs, diags = _check_closed_values(text, candidates, {}, reqs, [], [], MasterResolver())
    assert [r["type"] for r in reqs] == ["REGION"]
    assert [(d["code"], d["reason"], d["names"]) for d in diags] == [("UNMAPPED_INDUSTRY", "ALTERNATIVE_UNRESOLVED", ["산림조합"])]


def test_unresolved_or_unused_industry_stays_for_review():
    """(가) 업종 같은 이름을 코드로 못 바꿨거나, 찾은 코드를 모델이 '관련 없음' 으로 두면 확인 필요로 남긴다."""
    from bidengine.labeling.closed_first import _check_closed_values

    text = "나. 수중공사업을 등록한 업체"
    reqs, diags = _check_closed_values(text, scan_candidates(text, MasterResolver()), {}, [], [], [], MasterResolver())
    assert reqs == [] and [d["reason"] for d in diags] == ["INDUSTRY_NAME_UNRESOLVED"]
    # 열린 조건(등록 이름)으로 담았으면 사용자가 확인할 항목이 됐으니 공백을 더하지 않는다.
    _reqs, diags = _check_closed_values(text, [], {}, [], [], [{"등록인증_raw": "수중공사업 등록"}], MasterResolver())
    assert diags == []

    text = "나. 상·하수도설비공사업(업종코드 4996)을 등록한 업체"
    candidates = scan_candidates(text, MasterResolver())
    roles = {c.id: ("NOT_RELATED", "") for c in candidates}
    _reqs, diags = _check_closed_values(text, candidates, roles, [], [], [], MasterResolver())
    assert [(d["reason"], d["values"]) for d in diags] == [("CANDIDATE_UNUSED", ["4996"])]
    # 이름 뒤 괄호에 코드가 있으면 이름은 푼 것이다.
    assert unresolved_industry_names(text, candidates, MasterResolver()) == []
    assert unresolved_industry_names("라. 「신규사업자(개인사업자인 경우 사업자등록일)」", [], MasterResolver()) == []


def test_industry_named_as_a_standard_is_not_a_candidate():
    """'…운반업 및 중간처리업의 허가기준' 은 기준을 가리킨다 — 업종 요건 후보도, 못 푼 업종 이름도 아니다."""
    class Resolver6728:
        def code_for(self, name):
            return {"건설폐기물수집운반업": "6728"}.get("".join(name.replace("․", "").split()))

    text = ("② 폐기물중간처리업(건설폐기물, 업종코드 1253)으로 입찰참가자격을 등록한 자로서 「건설폐기물의 재활용촉진에 관한 법률"
            " 시행규칙」 제12조〔별표2〕 ‘건설폐기물수집․운반업 및 중간처리업의 허가기준’의 장비기준을 충족한 자")
    candidates = scan_candidates(text, Resolver6728())
    assert [(c.kind, c.value) for c in candidates] == [("INDUSTRY", "1253")]
    assert unresolved_industry_names(text, candidates, Resolver6728()) == []


def _required_everything(system, body, schema):
    """조항마다 '요구', 후보는 모두 필수, 열린 조건은 이름에 법령 조문이 든 등록 하나(소음으로 버려진다)."""
    import re as _re

    if schema is not SCHEMA:
        return {"clauses": []}
    clauses = []
    for block in body.split("\n\n"):
        head = block.split("\n", 1)[0]
        cid = _re.match(r"\[(C\d+)\]", head)
        if not cid:
            continue
        ids = [part.split()[0] for part in head.split("후보: ", 1)[1].split("; ")] if "후보: V" in head else []
        open_reqs = []
        if "관할" in block:
            open_reqs = [{name: None for name in SCHEMA["schema"]["properties"]["clauses"]["items"]["properties"]["open_requirements"]["items"]["required"]}
                         | {"유형": "등록요건", "등록인증_raw": "산업안전보건법 제74조에 따른 지도기관"}]
        clauses.append({"clause_id": cid.group(1), "polarity": "POSITIVE",
                        "candidates": [{"id": i, "role": "REQUIRED", "group": ""} for i in ids], "open_requirements": open_reqs})
    return {"clauses": clauses}


def _closed_first(section):
    return analyze_qualification_documents(
        QualificationAnalysisInput(notice_id="n", notice_version_id="v", documents=[
            QualificationDocumentInput(document_id="d", extracted_blocks=[{"block_index": 0, "text": section}])]),
        structured_extract=_required_everything, extraction_mode="closed_first", clause_selection="code",
        industry_resolver=Resolver(), summarize_gaps=False,
    )


def test_numbered_sub_items_under_any_of_are_alternatives_but_region_stays_common():
    """2026-10-07 표본 j: '다음 자격 중 어느 하나 … 1) … 2) …' 의 업종 둘이 모두 필수가 되어 틀린 미달이 났다."""
    section = """3. 입찰참가자격
가. 본점 소재지가 강릉시인 업체로서 다음 자격 중 어느 하나를 등록한 업체여야 합니다.
1) 조경식재·시설물공사업(업종코드 4993)
2) 조경공사업(업종코드 0005)
4. 입찰보증금"""
    requirements = _closed_first(section).requirements
    got = {(r.type, str(r.value), r.group_operator) for r in requirements}
    assert ("INDUSTRY", "4993", "ANY_OF") in got and ("INDUSTRY", "0005", "ANY_OF") in got
    assert ("REGION", "강릉시", "ALL_OF") in got        # 머리 조항의 소재지는 대안이 아니라 공통 조건
    # 판정에서 한 묶음이어야 한다 — 조항이 달라도 묶음 키가 같아야 4993 만 가진 회사가 충족이다.
    assert len({r.requirement_group_key for r in requirements if r.type == "INDUSTRY"}) == 1
    from datetime import date

    from bidengine.judgment.rules import CompanyProfileSnapshot, ProfileIndustryFact, judge_requirements
    company = CompanyProfileSnapshot(company_id="c", region_name="강원특별자치도 강릉시",
                                     industries=[ProfileIndustryFact(code="4993", name="조경식재ㆍ시설물공사업", verified=True)])
    assert judge_requirements(requirements, company, preflight_case_id="c", reference_date=date(2026, 10, 7),
                              coverage_complete=True).overall_status == "eligible"


def test_clause_whose_only_open_name_was_noise_stays_for_review():
    """이름(‘…제74조…’)만 소음으로 버렸고 다른 요건이 없으면 조항을 '요건으로 정리하지 못한 조항' 으로 남긴다."""
    section = """3. 입찰참가자격
④ 산업안전보건법 제74조에 따라 지정을 받은 재해예방전문기관 중 부산지방고용노동청 관할 지도기관으로 등록된 자
4. 입찰보증금"""
    result = _closed_first(section)
    assert any("관할" in gap.raw for gap in result.coverage.gaps)


class FamilyResolver(MasterResolver):
    FAMILIES = {"산림조합": ["4119", "4120"]}

    def family_codes(self, name):
        return self.FAMILIES.get("".join(name.split()), [])


def test_family_name_becomes_alternatives_with_the_other_industry():
    """'산림사업법인(숲가꾸기 및 병해충방제) 또는 산림조합' → 1475·4119·4120 중 하나(2026-10-08)."""
    from bidengine.labeling.closed_first import _closed_requirements

    text = "가. 「산림사업법인(숲가꾸기 및 병해충방제)」또는 산림조합법에 의하여 설립된「산림조합」으로 본점소재지가 곡성군"
    candidates = scan_candidates(text, FamilyResolver())
    assert {(c.value, c.family) for c in candidates if c.kind == "INDUSTRY"} == {("1475", ""), ("4119", "산림조합"), ("4120", "산림조합")}
    assert unresolved_industry_names(text, candidates, FamilyResolver()) == []
    # 모델이 1475 만 '필수' 로, 묶음 후보 하나만 '필수' 로 표시해도 셋이 한 대안 묶음이 된다.
    ids = {c.value: c.id for c in candidates}
    roles = {ids["1475"]: ("REQUIRED", ""), ids["4119"]: ("REQUIRED", ""), ids["4120"]: ("NOT_RELATED", ""),
             ids["곡성군"]: ("REQUIRED", "")}
    reqs, _diags = _closed_requirements("POSITIVE", text, candidates, roles)
    industries = {(r["value"], r.get("group")) for r in reqs if r["type"] == "INDUSTRY"}
    assert {value for value, _g in industries} == {"1475", "4119", "4120"}
    assert len({group for _v, group in industries}) == 1 and None not in {group for _v, group in industries}
    assert [r["value"] for r in reqs if r["type"] == "REGION"] == ["곡성군"]


def test_qualified_name_is_not_read_as_a_family():
    text = "가. 산림사업법인(숲가꾸기 및 병해충방제) 등록 업체"
    assert [c.family for c in scan_candidates(text, FamilyResolver()) if c.kind == "INDUSTRY"] == [""]


def test_sentence_pieces_from_spaceless_pdf_lines_are_not_industry_names():
    """'…울산광역시에둔사업자이어야' 같은 PDF 줄 덩어리는 업종 이름이 아니다(2026-10-08 표본 k). 진짜 이름은 그대로 잡는다."""
    text = "다.입찰공고일전일부터계약체결일까지주된영업소의소재지를계속경상남도또는울산광역시에둔사업자이어야합니다."
    assert unresolved_industry_names(text, [], MasterResolver()) == []
    assert unresolved_industry_names("나. 수중공사업을 등록한 업체", [], MasterResolver()) == ["수중공사업"]
