"""공고에 적힌 업종 이름과 글자가 겹치는 마스터 업종 이름을 고른다 — 모델이 그중에서 같은 업종을 고를 후보다.

이름이 정확히 같을 때만 코드를 주는 해석기(IndustryNameResolver)는 표기가 다른 같은 업종을 잇지 못한다.
"폐기물중간처리업(건설폐기물)" 과 마스터의 "건설폐기물 중간처리업", "위탁급식업" 과 "식품접객업(위탁급식영업)" 이 그렇다.
여기서는 겹치는 정도로 후보만 추린다. 어느 것이 같은 업종인지는 정하지 않는다.
"""
from __future__ import annotations

import re
from typing import Iterable

_DROP_RE = re.compile(r"[\s·ㆍ․∙,，./\-()（）\[\]]+")
MIN_OVERLAP = 0.5


def _grams(name: str) -> set[str]:
    text = _DROP_RE.sub("", name or "").casefold()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def rank_similar(name: str, rows: Iterable[tuple[str, str]], *, limit: int = 8) -> list[tuple[str, str]]:
    """(코드, 마스터 이름) 후보. 두 이름 중 짧은 쪽 글자쌍의 절반 이상이 다른 쪽에 들어 있어야 한다."""
    query = _grams(name)
    if len(query) < 2:
        return []
    scored: list[tuple[float, float, str, str]] = []
    for code, master in rows:
        grams = _grams(master)
        if len(grams) < 2:
            continue
        shared = len(query & grams)
        overlap = shared / min(len(query), len(grams))
        if shared >= 2 and overlap >= MIN_OVERLAP:   # 글자쌍 하나("행업")만 겹치는 짧은 이름은 뺀다
            scored.append((overlap, shared / len(query | grams), code, master))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [(code, master) for _overlap, _jaccard, code, master in scored[:limit]]


def similar_candidates(name: str, resolver: object, *, limit: int = 8) -> list[tuple[str, str]]:
    """해석기가 비슷한 이름 조회를 지원하면 그 후보, 아니면 빈 목록."""
    lookup = getattr(resolver, "similar", None)
    return list(lookup(name, limit)) if callable(lookup) else []
