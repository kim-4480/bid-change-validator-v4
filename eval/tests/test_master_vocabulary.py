from bideval.master_vocabulary import CsvIndustryNameResolver


def test_exact_master_names_resolve_ignoring_punctuation():
    resolver = CsvIndustryNameResolver()
    assert resolver.code_for("건설엔지니어링업(설계․사업관리-일반)") == "4967"
    assert resolver.code_for("건축공사업") == "0002"


def test_similar_but_different_names_do_not_resolve():
    resolver = CsvIndustryNameResolver()
    assert resolver.code_for("건축") is None
    assert resolver.code_for("의료기기") is None
