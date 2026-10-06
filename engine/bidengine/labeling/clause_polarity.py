"""조항의 극성(요구인가, 배제인가, 예외인가)을 모델에게 묻는다.

왜
--
안전 가드는 조항에 '또는'·'다만'·'아닌 자' 같은 낱말이 있으면 조항을 통째로 판정에서 뺀다. 2026-10-01 표본에서
놓친 지역·업종·품명번호·실적 요건 10건 중 8건이 이 가드에서 떨어졌다. 모델은 조항을 찾았고 값도 맞게 짚었다.

    "… 본점 소재지 또는 개인사업자의 사업자등록상 사업장 소재지가 경상남도에 있고 …"   → '또는' 은 주소를 보는 서류
    "… 무선송수신기(세부품명번호: 4319151001)으로 입찰참가 등록한 업체로서 … 제조 또는 납품 …" → 요건과 무관

같은 낱말이 문장마다 뜻이 다르다. "입찰참가자격 제한 중이 아닌 자" 는 결격 사유 확인이고, "종합건설사업자의 참여를
제한합니다" 는 배제이고, "실적은 최소요건으로 제한하지 않고" 는 요건이 아니다. 낱말 대조로는 가를 수 없어서
문장을 읽는 일은 모델에게 맡긴다.

무엇을 맡기고 무엇을 맡기지 않나
------------------------------
모델은 조항마다 다섯 값 중 하나만 고른다. 원문을 쓰지 않고, 값을 정하지 않고, 구조를 만들지 않는다.
값(지역 이름·업종코드)과 대안 묶음은 지금처럼 코드가 원문에서 정한다.

틀렸을 때의 비용이 한쪽으로 기운다. 배제 조항을 요구로 읽으면 틀린 확정이고, 요구를 배제로 읽으면 확인 필요가
하나 늘 뿐이다. 그래서 **POSITIVE 일 때만** 가드를 풀고, 나머지는 전부 확인 필요로 둔다. 호출이 실패하거나 답에
그 조항이 없으면 UNSURE 다.
"""
from __future__ import annotations

import hashlib
from collections.abc import MutableMapping
from typing import Any

from bidengine.labeling.requirement_extraction import StructuredExtractor

POLARITIES = ("POSITIVE", "EXCLUSION", "EXCEPTION", "NOT_REQUIREMENT", "EVALUATION", "UNSURE")
POLARITY_KEY = "_clause_polarity"
# 극성 프롬프트·값 목록을 바꾸면 올린다. 기억 열쇠에 섞여 예전 답을 새 규칙의 답으로 쓰지 않는다.
POLARITY_PROMPT_VERSION = "polarity-v2"
MAX_BODY_CHARS = 24_000

POLARITY_SCHEMA: dict[str, Any] = {
    "name": "clause_polarity",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "clauses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "clause_id": {"type": "string"},
                        "polarity": {"type": "string", "enum": list(POLARITIES)},
                    },
                    "required": ["clause_id", "polarity"],
                },
            }
        },
        "required": ["clauses"],
    },
}

POLARITY_SYSTEM_PROMPT = """너는 입찰공고 조항이 입찰 참가 업체에 무엇을 요구하는지 판별하는 도구다. 조항은 [P001] 같은 id 로 주어지고, 그 조항에서 뽑힌 요건 유형이 함께 적혀 있다. 조항마다 polarity 하나를 고른다.

- POSITIVE: 업체가 갖추어야 하는 자격·조건을 정한 조항이다. 문장 안의 '또는'·'다만'·괄호가 주소를 확인하는 서류, 기간, 대상 범위를 설명할 뿐이면 POSITIVE 다. 인정되는 대안을 나열하는 것("A 또는 B 를 등록한 자")도 POSITIVE 다.
- EXCLUSION: 해당하는 업체는 참가할 수 없다고 정한 조항이다(참여 제한, 참가 불가, 제외).
- EXCEPTION: 단서나 예외 때문에 일부 업체에는 그 요건이 적용되지 않거나 다른 것으로 갈음되는 조항이다.
- EVALUATION: 참가 자격이 아니라 점수를 매기는 기준이다. 제안서·기술능력 평가, 적격심사, 계약이행능력심사의 배점·평점·가점·감점 항목과 그 대상(실적, 인증, 인력, 신용등급)이 여기에 든다. 갖추지 못해도 입찰에는 참가할 수 있다. 조항이 놓인 위치(평가, 심사, 배점 같은 절)를 보고 판단한다.
- NOT_REQUIREMENT: 업체의 자격을 정한 것이 아니다. 절차·일정·제출 서류 안내, 납품할 물품이나 장비가 갖출 조건, 증명서의 유효기간 안내, 계약 후 과업을 수행할 때 지켜야 할 조건(투입 인력의 자격·경력·상주, 보고, 납품 방법)이 여기에 든다.
- UNSURE: 위 중 어느 것인지 분명하지 않다.

각 조항에는 그 조항이 놓인 절의 제목 경로(위치)가 함께 주어진다. 같은 문장도 참가자격 절에 있으면 요건이고, 평가 기준이나 과업 내용 절에 있으면 요건이 아니다.

규칙:
1. 받은 clause_id 를 그대로 쓴다. 없는 id 를 만들지 마라.
2. 원문을 쓰지 않는다. polarity 만 낸다.
3. 확신이 없으면 UNSURE 를 고른다. POSITIVE 는 그 조항이 업체가 갖추어야 할 조건임이 분명할 때만 고른다."""


def clause_key(text: str) -> str:
    """같은 문장은 같은 열쇠다 — 공백과 줄바꿈 차이는 무시한다."""
    return hashlib.sha256("".join((text or "").split()).encode("utf-8")).hexdigest()[:24]


def attach_clause_polarity(
    slots: list[dict[str, Any]],
    *,
    structured_extract: StructuredExtractor,
    memory: MutableMapping[str, str] | None = None,
    max_retry: int = 1,
) -> dict[str, Any]:
    """슬롯마다 그 조항의 극성을 붙인다(slot["_clause_polarity"]). 같은 조항은 한 번만 묻는다.

    memory 를 주면 조항 열쇠로 답을 기억한다. 같은 문장은 다시 돌려도, 다음 차수에서도 같은 답을 받는다.
    """
    known: MutableMapping[str, str] = memory if memory is not None else {}
    pending: dict[str, dict[str, Any]] = {}
    for slot in slots:
        raw = (slot.get("raw") or "").strip()
        if not raw:
            continue
        section = (slot.get("_section_path") or "").strip()
        key = clause_key(f"{section}\n{raw}" if section else raw)
        if key in known:
            continue
        entry = pending.setdefault(key, {"text": raw, "types": [], "section": section})
        slot_type = str(slot.get("유형") or "")
        if slot_type and slot_type not in entry["types"]:
            entry["types"].append(slot_type)

    asked = failed = 0
    batch: list[tuple[str, dict[str, Any]]] = []
    size = 0

    def flush() -> None:
        nonlocal batch, size, asked, failed
        if not batch:
            return
        ids = {f"P{index:03d}": key for index, (key, _entry) in enumerate(batch, start=1)}
        body = "\n\n".join(
            f"[{clause_id}] 위치: {entry['section'] or '알 수 없음'} | 요건 유형: {', '.join(entry['types']) or '미상'}\n{entry['text']}"
            for clause_id, (_key, entry) in zip(ids, batch)
        )
        answers: dict[str, str] = {}
        for _attempt in range(max_retry + 1):
            try:
                result = structured_extract(POLARITY_SYSTEM_PROMPT, body, POLARITY_SCHEMA)
            except Exception:  # noqa: BLE001 - 호출 실패는 UNSURE 로 떨어진다(확인 필요)
                continue
            for item in (result.get("clauses") or []) if isinstance(result, dict) else []:
                key = ids.get(str(item.get("clause_id") or "").strip("[] "))
                polarity = str(item.get("polarity") or "")
                if key is not None and polarity in POLARITIES:
                    answers[key] = polarity
            break
        asked += len(batch)
        for key, _entry in batch:
            if key in answers:
                known[key] = answers[key]
            else:
                failed += 1  # 기억하지 않는다 — 다음 실행에서 다시 묻는다
        batch, size = [], 0

    for key, entry in pending.items():
        length = len(entry["text"]) + 40
        if batch and size + length > MAX_BODY_CHARS:
            flush()
        batch.append((key, entry))
        size += length
    flush()

    counts: dict[str, int] = {}
    for slot in slots:
        raw = (slot.get("raw") or "").strip()
        if not raw:
            continue
        section = (slot.get("_section_path") or "").strip()
        polarity = known.get(clause_key(f"{section}\n{raw}" if section else raw), "UNSURE")
        slot[POLARITY_KEY] = polarity
        counts[polarity] = counts.get(polarity, 0) + 1
    return {"asked": asked, "unanswered": failed, "polarity_counts": counts}
