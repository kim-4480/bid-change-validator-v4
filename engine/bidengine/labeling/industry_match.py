"""코드로 바꾸지 못한 업종 이름을 모델이 마스터 후보 중에서 고른다(2026-10-10).

코드는 이름이 마스터와 정확히 같을 때만 업종코드를 준다. 공고는 같은 업종을 다르게 쓴다 — "폐기물중간처리업(건설폐기물)"
(마스터: 건설폐기물 중간처리업), "위탁급식업"(마스터: 식품접객업(위탁급식영업)). 표기마다 규칙을 더하는 대신, 글자가 겹치는
마스터 이름 몇 개를 후보로 주고 모델이 같은 업종을 고르게 한다.

모델이 할 수 있는 일은 후보 중 하나를 고르거나 '없음' 이라고 하는 것뿐이다. 후보에 없는 코드는 버린다. 고른 코드는 추론이라
판정기가 부적합의 근거로 쓰지 않는다(scope.evidence = "model_match": 맞으면 충족, 안 맞으면 확인 필요).
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, MutableMapping

INDUSTRY_MATCH_VERSION = "industry-match-v1"
NONE = "NONE"
MAX_ENTRIES = 24

SCHEMA: dict[str, Any] = {
    "name": "industry_match",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["matches"],
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "code"],
                    "properties": {"id": {"type": "string"}, "code": {"type": "string"}},
                },
            }
        },
    },
}

SYSTEM_PROMPT = """너는 입찰공고에 적힌 업종 이름을 나라장터 업종 목록과 맞추는 도구다. 항목마다 공고 조항, 그 조항에 적힌 업종 이름, 그리고 나라장터 업종 후보(코드: 이름)가 주어진다.

할 일: 공고의 이름이 가리키는 업종(면허·등록·허가·신고·지정)이 후보 중 어느 것과 **같은 업종**인지 고른다.
- 같은 업종이면 그 후보의 코드 4자리를 답한다. 표기 순서나 띄어쓰기, 괄호 위치만 다른 것은 같은 업종이다.
  예: "폐기물중간처리업(건설폐기물)" = "건설폐기물 중간처리업", "위탁급식업" = "식품접객업(위탁급식영업)".
- 괄호 세부명이 다르면 다른 업종이다. "폐기물수집·운반업(건설폐기물)" 은 "폐기물수집·운반업(생활폐기물)" 이 아니다.
- 낱말이 비슷할 뿐 같은 업종이 아니거나, 조항에서 그 이름이 업종 자격이 아니면(법 이름, 사업 이름, 기관 이름, 기업 종류) NONE 이라고 답한다.
- 확신이 없으면 NONE 이라고 답한다. 후보에 없는 코드는 쓰지 않는다.

모든 항목에 대해 {"id": 항목 id, "code": 코드 또는 "NONE"} 을 돌려준다."""


def match_key(clause: str, name: str, options: list[tuple[str, str]]) -> str:
    body = (
        INDUSTRY_MATCH_VERSION + "\n" + "".join((clause or "").split()) + "\n" + "".join(name.split())
        + "\n" + ";".join(code for code, _ in options)
    )
    return "MATCH:" + hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


def match_industry_names(
    entries: list[tuple[str, str, list[tuple[str, str]]]],
    *,
    structured_extract: Callable[[str, str, dict], dict],
    memory: MutableMapping[str, Any] | None = None,
    max_retry: int = 1,
) -> dict[str, str | None]:
    """entries: (조항, 이름, 후보[(코드, 마스터 이름)]). 돌려주는 값: {match_key: 코드 또는 None}.

    기억에 있는 항목은 묻지 않는다. 호출이 실패한 항목은 None 이고 기억하지 않는다 — 다음 분석에서 다시 묻는다.
    """
    known: MutableMapping[str, Any] = memory if memory is not None else {}
    out: dict[str, str | None] = {}
    pending: dict[str, tuple[str, str, list[tuple[str, str]]]] = {}
    for clause, name, options in entries:
        key = match_key(clause, name, options)
        if key in known:
            stored = known[key]
            out[key] = (stored.get("code") if isinstance(stored, dict) else None) or None
        elif options:
            pending.setdefault(key, (clause, name, options))
    items = list(pending.items())
    for start in range(0, len(items), MAX_ENTRIES):
        batch = items[start:start + MAX_ENTRIES]
        ids = {f"N{index:02d}": item for index, item in enumerate(batch, start=1)}
        body = "\n\n".join(
            f"[{entry_id}] 업종 이름: {name}\n조항: {' '.join(clause.split())[:600]}\n후보: "
            + "; ".join(f"{code}: {master}" for code, master in options)
            for entry_id, (_key, (clause, name, options)) in ids.items()
        )
        result = None
        for _attempt in range(max_retry + 1):
            try:
                result = structured_extract(SYSTEM_PROMPT, body, SCHEMA)
                break
            except Exception:  # noqa: BLE001 - 호출 실패는 '고르지 못함' 으로 둔다
                result = None
        if not isinstance(result, dict):
            for key, _entry in batch:
                out[key] = None
            continue
        answered = {
            str(m.get("id")): str(m.get("code") or "").strip()
            for m in result.get("matches") or [] if isinstance(m, dict)
        }
        for entry_id, (key, (_clause, _name, options)) in ids.items():
            code = answered.get(entry_id, NONE)
            chosen = code if code in {c for c, _ in options} else None   # 후보에 없는 코드는 버린다
            out[key] = chosen
            known[key] = {"code": chosen}
    return out
