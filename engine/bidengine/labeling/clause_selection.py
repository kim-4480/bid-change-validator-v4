"""문서 전체의 조항 가운데 참가자격 조항을 모델이 고른다.

왜
--
코드는 제목("3. 입찰참가자격")과 키워드로 자격 절을 고른다. 자격 조건이 그 절 밖에 적힌 공고가 있다.

    "1. 입찰에 부치는 사항 … 마. 본 입찰은 지역제한 입찰이며 … [충청남도] 또는 [세종특별시]에 있는 업체"
    "3. 계약 및 입찰방법 … 바. 공동수급이 허용되지 않습니다."

코드가 고르지 않은 조항은 모델에 닿지 않고, 빠졌다는 흔적도 남지 않는다(2026-10-01~02 표본).

무엇을 맡기고 무엇을 맡기지 않나
------------------------------
조항의 경계와 원문은 코드가 정한다(enumerate_clauses). 모델은 조항 목록을 보고 id 만 고른다. 원문을 쓰거나
경계를 바꿀 수 없고, 없는 id 는 무시된다. 고르는 데는 조항 앞부분이면 충분해서 앞 300자만 보낸다.

호출이 실패하면 None 을 돌려준다 — 부르는 쪽은 코드 선택으로 돌아간다.
"""
from __future__ import annotations

import hashlib
from collections.abc import MutableMapping
from typing import Any

from bidengine.clauses.enumerate import Clause
from bidengine.labeling.requirement_extraction import StructuredExtractor

CLAUSE_PREVIEW_CHARS = 300
SELECTION_BATCH_CHARS = 40_000

SELECTION_SCHEMA: dict[str, Any] = {
    "name": "eligibility_clause_selection",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {"clause_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["clause_ids"],
    },
}

SELECTION_SYSTEM_PROMPT = """너는 입찰공고 문서에서 참가자격 조항을 고르는 도구다. 조항은 이미 [S0001] 같은 id 로 나뉘어 있다.
규칙:
1. 입찰에 참가하려는 업체가 갖춰야 하는 자격·조건을 정한 조항의 id 만 고른다. 업종·면허·등록·인증 보유, 본점 소재지(지역제한), 기업 규모와 그 참여 제한, 실적, 인력, 공동수급·공동계약의 허용 여부가 그런 조건이다.
2. 제목, 일정, 제출 서류 목록, 입찰 방법과 절차 안내, 무효·유의 사항, 규격과 사양, 평가 기준, 계약 조건, 서식은 고르지 않는다.
3. 받은 id 를 그대로 쓴다. 없는 id 를 만들지 마라.
4. 원문은 쓰지 않는다. id 만 낸다. 참가자격 조항이 없으면 빈 배열."""


def selection_key(text: str) -> str:
    """같은 문장은 같은 열쇠다 — 공백과 줄바꿈 차이는 무시한다."""
    return hashlib.sha256("".join((text or "").split()).encode("utf-8")).hexdigest()[:24]


def select_requirement_clauses(
    clauses: list[Clause],
    *,
    structured_extract: StructuredExtractor,
    memory: MutableMapping[str, bool] | None = None,
    max_retry: int = 1,
) -> set[str] | None:
    """참가자격으로 고른 조항의 열쇠(selection_key) 집합. 호출이 한 번이라도 끝내 실패하면 None.

    memory 를 주면 조항 열쇠마다 고름/안 고름을 기억한다. 같은 문장은 다시 돌려도, 다음 차수에서도 같은
    결정을 받고, 이미 아는 조항은 다시 묻지 않는다.
    """
    known: MutableMapping[str, bool] = memory if memory is not None else {}
    pending: dict[str, str] = {}
    for clause in clauses:
        key = selection_key(clause.text)
        if key not in known and key not in pending:
            pending[key] = clause.text

    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for key, text in pending.items():
        length = min(len(text), CLAUSE_PREVIEW_CHARS) + 12
        if current and size + length > SELECTION_BATCH_CHARS:
            batches.append(current)
            current, size = [], 0
        current.append((key, text))
        size += length
    if current:
        batches.append(current)

    counter = 0
    for batch in batches:
        ids: dict[str, str] = {}
        parts = []
        for key, text in batch:
            counter += 1
            clause_id = f"S{counter:04d}"
            ids[clause_id] = key
            parts.append(f"[{clause_id}]\n{text[:CLAUSE_PREVIEW_CHARS]}")
        picked: set[str] | None = None
        for _attempt in range(max_retry + 1):
            try:
                result = structured_extract(SELECTION_SYSTEM_PROMPT, "\n\n".join(parts), SELECTION_SCHEMA)
            except Exception:  # noqa: BLE001 - 호출 실패는 None 으로 알린다
                continue
            picked = {
                ids[clause_id]
                for clause_id in (str(item).strip("[] ") for item in (result.get("clause_ids") or []))
                if clause_id in ids
            } if isinstance(result, dict) else set()
            break
        if picked is None:
            return None
        for key in ids.values():
            known[key] = key in picked

    return {selection_key(clause.text) for clause in clauses if known.get(selection_key(clause.text))}
