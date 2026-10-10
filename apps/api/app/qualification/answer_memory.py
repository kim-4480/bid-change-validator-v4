"""DB-backed engine memories: the first answer per clause wins, across requests.

The engine asks the model three things per clause — the requirement labels, the
polarity, and whether the clause is a requirement at all — and accepts a
``MutableMapping`` for each so that the same clause gets the same answer. Kept in
process memory those answers vanish between requests; here they live in
``clause_answer_memory``. Writes use ``ON CONFLICT DO NOTHING``: when two analyses
race on the same clause the first stored answer stays and both read it back.

Writes join the caller's transaction, so they are committed together with the
analysis run (and dropped with it if the run fails).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, MutableMapping
from typing import Any

from sqlalchemy import Column, DateTime, MetaData, Table, Text, func, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session

from ..models import IndustryCode

_metadata = MetaData()
clause_answer_memory = Table(
    "clause_answer_memory",
    _metadata,
    Column("kind", Text, primary_key=True),
    Column("clause_key", Text, primary_key=True),
    Column("answer", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

# gap_summary: 요건으로 정리하지 못한 조항의 종류·확인용 문장(2026-10-07). 같은 조항은 같은 설명이 나오게 기억한다.
MEMORY_KINDS = ("label", "polarity", "selection", "gap_summary")


class DbAnswerMemory(MutableMapping[str, Any]):
    """One engine memory (labels, polarity or selection) stored in ``clause_answer_memory``."""

    def __init__(self, db: Session, kind: str) -> None:
        if kind not in MEMORY_KINDS:
            raise ValueError(f"unknown memory kind: {kind}")
        self._db = db
        self._kind = kind
        self._cache: dict[str, Any] = {}

    def _load(self, key: str) -> bool:
        if key in self._cache:
            return True
        answer = self._db.execute(
            select(clause_answer_memory.c.answer).where(
                clause_answer_memory.c.kind == self._kind,
                clause_answer_memory.c.clause_key == key,
            )
        ).scalar_one_or_none()
        if answer is None:
            return False
        self._cache[key] = answer
        return True

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._load(key)

    def __getitem__(self, key: str) -> Any:
        if not self._load(key):
            raise KeyError(key)
        return self._cache[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if self._load(key):
            return  # first answer wins
        self._db.execute(
            insert(clause_answer_memory)
            .values(kind=self._kind, clause_key=key, answer=value)
            .on_conflict_do_nothing(index_elements=["kind", "clause_key"])
        )
        self._cache.pop(key, None)
        self._load(key)  # read back whichever answer was stored first

    def __delitem__(self, key: str) -> None:
        raise TypeError("clause answers are append-only")

    def __iter__(self) -> Iterator[str]:
        return iter(self._cache)

    def __len__(self) -> int:
        return len(self._cache)


_IGNORED = re.compile(r"[\s·ㆍ․,，./\-]+")


def _normalize_name(name: str) -> str:
    return _IGNORED.sub("", name or "").casefold()


class DbIndustryNameResolver:
    """``IndustryNameResolver`` over the ``industry_codes`` master table.

    Exact match after ignoring spaces and middle dots ("철근·콘크리트공사업" ==
    "철근ㆍ콘크리트공사업"). A name that maps to more than one code is not resolved.
    """

    def __init__(self, db: Session) -> None:
        by_name: dict[str, str] = {}
        ambiguous: set[str] = set()
        rows = list(db.execute(select(IndustryCode.code, IndustryCode.name).where(IndustryCode.active.is_(True))))
        from bidengine.normalization.industry_inclusion import inclusion_index

        self._including = inclusion_index(
            (code, (raw or {}).get("inclsnLcns") if isinstance(raw, dict) else None)
            for code, raw in db.execute(select(IndustryCode.code, IndustryCode.raw_json).where(IndustryCode.active.is_(True)))
        )
        from bidengine.normalization.industry_family import family_index

        self._families = family_index(((code, name) for code, name in rows), _normalize_name)
        self._rows = [(code, name) for code, name in rows]
        for code, name in rows:
            key = _normalize_name(name)
            if key in by_name and by_name[key] != code:
                ambiguous.add(key)
            by_name.setdefault(key, code)
        for key in ambiguous:
            by_name.pop(key, None)
        self._by_name = by_name

    def code_for(self, name: str) -> str | None:
        return self._by_name.get(_normalize_name(name))

    def family_codes(self, name: str) -> list[str]:
        """세부명 없이 쓴 묶음 이름("산림조합")의 세부명 업종 코드들. 없으면 빈 목록."""
        return self._families.get(_normalize_name(name), [])

    def including_codes(self, code: str) -> list[str]:
        """이 업종을 포함하는 업종코드들(포함 면허). 그 업종을 가진 회사는 이 업종 자격도 갖춘 것으로 본다."""
        return self._including.get(code, [])

    def similar(self, name: str, limit: int = 8) -> list[tuple[str, str]]:
        """글자가 겹치는 마스터 업종 (코드, 이름) 후보. 같은 업종인지는 정하지 않는다."""
        from bidengine.normalization.industry_similar import rank_similar

        return rank_similar(name, self._rows, limit=limit)
