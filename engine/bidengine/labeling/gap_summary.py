"""요건으로 정리하지 못한 조항(공백)을 사용자가 확인할 수 있는 문장으로 바꾼다.

공백은 원문 조각 그대로라("다. 납품할 종자를 생산할 수 있는 생산시설(친어지, 부화지, 치어사육지)을 갖춘 자로서 …")
사용자가 무엇을 확인해야 하는지 바로 알기 어렵다(2026-10-07 사용자 요청). 모델이 앞 문맥까지 보고 조항이 어떤
종류인지 분류하고, 확인할 내용을 한 문장으로 쓴다.

판정은 하지 않는다 — 요건도, 참가 가능 여부도 바꾸지 않는다. 화면에 보여 줄 설명만 만든다. 그래도 사용자가 이
문장을 믿고 확인하므로 원문에 없는 내용을 쓰면 안 된다. 코드가 검사한다:
  - 문장에 나온 숫자는 모두 원문에 있어야 한다(금액·기간·인원 지어내기 방지).
  - 참가 가능·불가 같은 판정 말을 쓰지 않는다.
  - 너무 긴 문장은 쓰지 않는다.
통과하지 못하면 설명 없이 원문만 보여 준다. 같은 조항은 같은 설명이 나오도록 답을 기억한다.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, MutableMapping

GAP_SUMMARY_VERSION = "gap-summary-v2"
MAX_SUMMARY_CHARS = 140
CONTEXT_CHARS = 220

CATEGORIES: dict[str, str] = {
    "LICENSE_PERMIT": "면허·허가·등록",
    "CERTIFICATION": "인증·확인서",
    "PERFORMANCE": "실적",
    "STAFF": "인력",
    "FACILITY_EQUIPMENT": "시설·장비",
    "PRODUCT_CONDITION": "납품 물품 조건",
    "INDUSTRY_ALTERNATIVE": "업종 대안·예외",
    "REGION_SIZE": "소재지·기업 규모",
    "CONDITIONAL": "조건부 자격",
    "BASIC_QUALIFICATION": "법령상 기본 자격·결격",
    "PROCEDURE": "입찰 절차",
    "DOCUMENT": "제출 서류",
    "OTHER": "기타",
}

SCHEMA: dict[str, Any] = {
    "name": "gap_summary",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "summary": {"type": "string"},
                    },
                    "required": ["id", "category", "summary"],
                },
            }
        },
        "required": ["items"],
    },
}

SYSTEM_PROMPT = """너는 입찰공고의 참가자격 조항을 사용자에게 설명하는 도구다. 조항은 [G1] 같은 id 로 주어지고, 각 조항 앞에 그
조항이 놓인 앞 문맥(절 제목·앞 줄)이 붙어 있다. 이 조항들은 프로그램이 요건으로 정리하지 못한 것이라 사용자가 원문을
보고 직접 확인해야 한다.

조항마다 두 가지를 답한다.
1. category: 조항이 무엇에 관한 것인지.
   LICENSE_PERMIT(면허·허가·등록), CERTIFICATION(인증·확인서), PERFORMANCE(실적), STAFF(인력),
   FACILITY_EQUIPMENT(시설·장비), PRODUCT_CONDITION(납품 물품 조건), INDUSTRY_ALTERNATIVE(업종 대안·예외),
   REGION_SIZE(소재지·기업 규모), CONDITIONAL(특정 경우에만 적용되는 조건부 자격),
   BASIC_QUALIFICATION(법령·기관 규정이 정한 기본 자격이나 결격 사유), PROCEDURE(입찰 등록·서류 제출 같은 절차),
   DOCUMENT(제출 서류), OTHER(위 어디에도 맞지 않을 때만)
2. summary: 사용자가 무엇을 확인해야 하는지 한 문장. 원문에 있는 사실만 쓴다.
   - "~를 갖추어야 합니다", "~인 경우 ~해야 합니다" 처럼 공고가 요구하는 내용을 쓴다. 특정 경우에만 적용되면 그 경우를 앞에 쓴다.
   - 원문에 없는 숫자·기간·금액·이름을 만들지 않는다. 원문의 숫자는 그대로 옮긴다.
   - 참가할 수 있다/없다를 판단하지 않는다. 회사가 조건을 갖췄는지도 말하지 않는다.
   - 140자 이내. 법령 조문 번호는 꼭 필요할 때만 쓴다.
받은 id 를 그대로 쓰고, 받은 조항마다 하나씩 답한다."""

_JUDGMENT_WORDS_RE = re.compile(r"참가\s*(?:가능|불가)|참여\s*(?:가능|불가)|적합합니다|부적합|자격이\s*(?:있|없)습니다")


def _compact(text: str) -> str:
    return "".join((text or "").split())


def summary_key(raw: str, context: str) -> str:
    """기억 키: 조항 원문과 앞 문맥(띄어쓰기 무시). 같은 조항이라도 문맥이 다르면 다시 묻는다."""
    body = GAP_SUMMARY_VERSION + "\n" + _compact(context)[-CONTEXT_CHARS:] + "\n" + _compact(raw)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:24]


def summary_is_grounded(summary: str, raw: str, context: str = "") -> bool:
    """설명이 원문에 기대고 있는가. 숫자는 모두 원문(또는 앞 문맥)에 있어야 하고, 판정 말을 쓰지 않는다."""
    text = " ".join((summary or "").split())
    if not text or len(text) > MAX_SUMMARY_CHARS or _JUDGMENT_WORDS_RE.search(text):
        return False
    source_digits = _compact(raw + " " + context)
    source_digits = re.sub(r"[,，]", "", source_digits)
    for number in re.findall(r"\d[\d,，.]*", text):
        if re.sub(r"[,，]", "", number).rstrip(".") not in source_digits:
            return False
    return True


def context_before(raw: str, chunks: list[dict[str, Any]]) -> str:
    """조항이 들어 있는 청크에서 조항 바로 앞 문맥(절 제목·앞 줄)을 가져온다. 못 찾으면 빈 문자열."""
    target = _compact(raw)[:40]
    if not target:
        return ""
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        compact = _compact(text)
        at = compact.find(target)
        if at < 0:
            continue
        # 띄어쓰기를 지운 위치를 원문 위치로 되돌린다.
        seen = 0
        for index, char in enumerate(text):
            if not char.isspace():
                if seen == at:
                    return " ".join(text[max(0, index - CONTEXT_CHARS):index].split())
                seen += 1
    return ""


def summarize_gaps(
    gaps: list[dict[str, str]],
    *,
    structured_extract: Callable[[str, str, dict[str, Any]], dict[str, Any]],
    memory: MutableMapping[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    """공백마다 {category, summary}. 입력은 [{"raw", "context"}]. 결과 키는 summary_key.

    모델 호출이 실패하거나 설명이 원문 검사를 통과하지 못한 조항은 결과에 없다(화면은 원문만 보여 준다).
    통과한 답만 기억한다.
    """
    known: MutableMapping[str, Any] = memory if memory is not None else {}
    out: dict[str, dict[str, str]] = {}
    pending: list[tuple[str, dict[str, str]]] = []
    for gap in gaps:
        key = summary_key(gap["raw"], gap.get("context", ""))
        if key in out or any(key == k for k, _ in pending):
            continue
        if key in known:
            out[key] = dict(known[key])
        else:
            pending.append((key, gap))
    if not pending:
        return out
    ids = {f"G{index + 1}": item for index, item in enumerate(pending)}
    body = "\n\n".join(
        f"[{gid}] 앞 문맥: {gap.get('context') or '없음'}\n조항: {' '.join(gap['raw'].split())}" for gid, (_key, gap) in ids.items()
    )
    answer = None
    for _attempt in range(2):  # 한 번 실패는 흔하다(표본 j 에서 설명이 통째로 빠졌다). 한 번 더 묻는다.
        try:
            answer = structured_extract(SYSTEM_PROMPT, body, SCHEMA)
            break
        except Exception:  # noqa: BLE001 — 설명은 부가 정보다. 실패해도 분석은 그대로 낸다.
            continue
    if answer is None:
        return out
    for item in (answer or {}).get("items") or []:
        found = ids.get(str(item.get("id")))
        if found is None:
            continue
        key, gap = found
        category = item.get("category") if item.get("category") in CATEGORIES else "OTHER"
        summary = " ".join(str(item.get("summary") or "").split())
        if not summary_is_grounded(summary, gap["raw"], gap.get("context", "")):
            continue
        out[key] = {"category": category, "summary": summary}
        known[key] = out[key]
    return out


def category_label(category: str | None) -> str | None:
    return CATEGORIES.get(category or "")


__all__ = ["CATEGORIES", "GAP_SUMMARY_VERSION", "context_before", "summarize_gaps", "summary_is_grounded", "summary_key"]
