"""포함 면허: 어떤 업종을 가진 회사가 다른 업종의 자격도 갖춘 것으로 인정되는 관계(2026-10-10).

나라장터 업종 마스터의 `inclsnLcns` 에 들어 있다.

    "[1^0002^건축공사업^0003^토목건축공사업],[2^0001^토목공사업^0003^토목건축공사업]"
     └ 순번 ^ 포함되는 업종코드 ^ 이름 ^ 포함하는 업종코드 ^ 이름

토목건축공사업(0003)을 가진 회사는 건축공사업(0002)·토목공사업(0001)을 요구하는 입찰에 참가할 수 있다. 공고가
"건축공사업" 만 적어도 그렇다 — 이 관계를 모르면 토목건축공사업만 가진 회사가 부적합으로 나온다.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

_ENTRY_RE = re.compile(r"\[([^\[\]]*)\]")
_CODE_RE = re.compile(r"[0-9]{4}")


def inclusion_index(rows: Iterable[tuple[str, str | None]]) -> dict[str, list[str]]:
    """(업종코드, inclsnLcns 문자열) 목록 → {포함되는 코드: [포함하는 코드…]}. 형식이 다른 항목은 건너뛴다."""
    parents: dict[str, set[str]] = defaultdict(set)
    for _code, text in rows:
        for entry in _ENTRY_RE.findall(text or ""):
            fields = entry.split("^")
            if len(fields) != 5:
                continue
            child, parent = fields[1].strip(), fields[3].strip()
            if _CODE_RE.fullmatch(child) and _CODE_RE.fullmatch(parent) and child != parent:
                parents[child].add(parent)
    return {child: sorted(codes) for child, codes in parents.items()}


def including_codes(code: str, resolver: object) -> list[str]:
    """해석기가 포함 면허 조회를 지원하면 그 코드를 포함하는 업종코드들, 아니면 빈 목록."""
    lookup = getattr(resolver, "including_codes", None)
    return list(lookup(code)) if callable(lookup) else []
