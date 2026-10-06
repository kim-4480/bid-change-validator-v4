"""조항 답 기억(clause_answer_memory): 같은 조항은 요청이 바뀌어도 같은 답이다."""
from uuid import uuid4

import pytest

from apps.api.app.database import SessionLocal
from apps.api.app.qualification.answer_memory import DbAnswerMemory, DbIndustryNameResolver


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()  # 테스트가 쓴 답은 남기지 않는다
        session.close()


def test_first_answer_wins_and_is_read_back(db) -> None:
    key = f"test-{uuid4().hex}"
    memory = DbAnswerMemory(db, "label")
    assert key not in memory
    memory[key] = [{"유형": "지역요건", "지역_raw": "서울특별시"}]
    memory[key] = [{"유형": "기타요건"}]  # 나중 답은 버린다
    again = DbAnswerMemory(db, "label")  # 새 요청
    assert key in again
    assert again[key] == [{"유형": "지역요건", "지역_raw": "서울특별시"}]
    assert again.get(f"missing-{uuid4().hex}") is None


def test_kinds_do_not_share_answers(db) -> None:
    key = f"test-{uuid4().hex}"
    DbAnswerMemory(db, "polarity")[key] = "POSITIVE"
    assert key not in DbAnswerMemory(db, "selection")
    assert DbAnswerMemory(db, "polarity")[key] == "POSITIVE"


def test_unknown_kind_is_rejected(db) -> None:
    with pytest.raises(ValueError):
        DbAnswerMemory(db, "anything")


def test_industry_names_resolve_against_the_master_table(db, seed_required_master_codes) -> None:
    resolver = DbIndustryNameResolver(db)
    assert resolver.code_for("건축 공사업") == "0002"
    assert resolver.code_for("없는업종") is None
