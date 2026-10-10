"""업종 묶음 이름: 마스터에 괄호 세부명이 붙은 이름으로만 있는 업종의 앞부분.

"산림조합" 은 마스터에 '산림조합(지역조합) 4119', '산림조합(전문조합) 4120' 으로만 있다. 공고가 세부명 없이 "산림조합" 이라고
쓰면 그 세부명 업종 중 어느 것이든 된다는 뜻이다(2026-10-08 — 산림 공고마다 이 이름을 코드로 못 바꿔 확인 필요로 남았다).
묶음은 세부명 업종이 둘 이상이고 앞부분만으로 된 마스터 이름이 따로 없을 때만 만든다(있으면 그것이 정확한 이름이다).
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Callable, Iterable

_QUALIFIED_RE = re.compile(r"^\s*(.+?)\s*\(([^()]+)\)\s*$")


def family_index(rows: Iterable[tuple[str, str]], normalize: Callable[[str], str]) -> dict[str, list[str]]:
    """(코드, 이름) 목록 → {정규화한 앞부분: [세부명 업종 코드…]}."""
    rows = list(rows)
    exact = {normalize(name) for _code, name in rows}
    groups: dict[str, set[str]] = defaultdict(set)
    for code, name in rows:
        match = _QUALIFIED_RE.match(name or "")
        if match:
            groups[normalize(match.group(1))].add(code)
    return {base: sorted(codes) for base, codes in groups.items() if len(codes) >= 2 and base not in exact}


def family_codes(name: str, resolver: object) -> list[str]:
    """해석기가 묶음 조회를 지원하면 묶음 코드, 아니면 빈 목록."""
    lookup = getattr(resolver, "family_codes", None)
    return list(lookup(name)) if callable(lookup) else []
