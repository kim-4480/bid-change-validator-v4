"""코드로 못 바꾼 업종 이름을 모델이 마스터 후보 중에서 고른다(2026-10-10)."""
from bidengine.labeling.closed_first import apply_matches, names_to_match, scan_candidates
from bidengine.labeling.industry_match import match_industry_names, match_key
from bidengine.normalization.industry_similar import rank_similar

ROWS = [("1253", "건설폐기물 중간처리업"), ("6728", "건설폐기물 수집·운반업"), ("1224", "폐기물수집·운반업(생활폐기물)"),
        ("1226", "폐기물수집·운반업(사업장배출시설폐기물)"), ("1450", "식품접객업(위탁급식영업)"), ("3809", "은행업"), ("0037", "전기공사업")]


class Resolver:
    def code_for(self, name):
        key = "".join(name.split())
        return next((code for code, master in ROWS if "".join(master.split()) == key), None)

    def similar(self, name, limit=8):
        return rank_similar(name, ROWS, limit=limit)


CLAUSE = "1) 건설폐기물의 재활용촉진에 관한 법률 제21조의 규정에 의한 폐기물중간처리업(건설폐기물) 허가를 받은 업체"


def test_similar_names_are_candidates_not_answers():
    assert rank_similar("폐기물중간처리업(건설폐기물)", ROWS)[0] == ("1253", "건설폐기물 중간처리업")
    assert rank_similar("위탁급식업", ROWS) == [("1450", "식품접객업(위탁급식영업)")]
    assert rank_similar("특별법인", ROWS) == []
    assert ("3809", "은행업") not in rank_similar("종합여행업", ROWS)      # 글자쌍 하나만 겹친다


def test_the_qualifier_in_brackets_is_asked_with_the_name():
    resolver = Resolver()
    asked = names_to_match(CLAUSE, scan_candidates(CLAUSE, resolver), resolver)
    assert [(name, full) for name, full, _options in asked] == [("폐기물중간처리업", "폐기물중간처리업(건설폐기물)")]
    assert asked[0][2][0][0] == "1253"


def test_a_chosen_code_becomes_a_weak_candidate():
    resolver = Resolver()
    candidates = scan_candidates(CLAUSE, resolver)
    asked = names_to_match(CLAUSE, candidates, resolver)
    calls = []

    def model(_system, body, _schema):
        calls.append(body)
        return {"matches": [{"id": "N01", "code": "1253"}]}

    memory: dict = {}
    entries = [(CLAUSE, full, options) for _name, full, options in asked]
    answers = match_industry_names(entries, structured_extract=model, memory=memory)
    merged = apply_matches(CLAUSE, candidates, asked, answers)
    assert [(c.value, c.evidence) for c in merged if c.kind == "INDUSTRY"] == [("1253", "model_match")]
    assert [c.id for c in merged] == [f"V{i}" for i in range(1, len(merged) + 1)]
    # 같은 조항은 다시 묻지 않는다.
    assert match_industry_names(entries, structured_extract=model, memory=memory) == answers and len(calls) == 1


def test_a_code_outside_the_candidates_is_dropped():
    options = [("1253", "건설폐기물 중간처리업")]
    for answer in ("9999", "NONE", ""):
        result = match_industry_names([(CLAUSE, "폐기물중간처리업(건설폐기물)", options)],
                                      structured_extract=lambda *_: {"matches": [{"id": "N01", "code": answer}]}, memory={})
        assert result == {match_key(CLAUSE, "폐기물중간처리업(건설폐기물)", options): None}


def test_a_failed_call_is_not_remembered():
    def broken(*_):
        raise RuntimeError("boom")

    memory: dict = {}
    result = match_industry_names([(CLAUSE, "위탁급식업", [("1450", "식품접객업(위탁급식영업)")])], structured_extract=broken, memory=memory)
    assert list(result.values()) == [None] and memory == {}
