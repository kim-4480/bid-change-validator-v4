"""Second-tier clause finding: retrieval plus a quoted source sentence.

The lexicon patterns in `standard_diff` catch wording they have seen before. A
notice that says "품질을 보장하며 발생하는 문제를 자비로 해결한다" is a warranty clause
without using a single warranty word, and no amount of synonym-listing reaches it.

So when tier one produced no confident verdict for a rule, this searches the
chunks the regexes never looked at, by embedding similarity against the standard
clause, and asks the model for one thing only: **the sentence**. It quotes; it
does not decide.

The division of labour is the same one used for requirement extraction:

- The model marks whether the text is on topic and copies the source sentence
  and any figure as written. It never converts a number and never judges.
- Code verifies the quote actually occurs in the chunk, and discards it if not.
- Code normalizes the figure and compares it against the threshold — using the
  exact same comparison tier one uses. Only the way the sentence was *found*
  differs.

It is a separate module because when it runs matters as much as what it does.
Folding it into `standard_diff` would blur the cost boundary: this path costs an
embedding call plus up to three model calls per unresolved rule, and it must stay
obvious that a rule with a confident answer never reaches it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from bidengine.normalization import extract_values
from bidengine.providers.embeddings import Embedder, similarity_matrix
from bidengine.labeling.requirement_extraction import StructuredExtractor
from bidengine.clause_review.contracts import ClauseVerdict


# Stricter than tier one: narrow the candidates hard before paying for a model.
# This value is calibrated for real embeddings and does not transfer to the
# offline fallback — see `_gate_candidates`.
SIMILARITY_THRESHOLD = 0.22
TOP_K = 3

# How much of a quote must match the source. Long quotes get truncated by the
# model more often than they get fabricated, so the head is what is checked.
_QUOTE_PREFIX_CHARS = 80

EVIDENCE_SCHEMA: dict[str, Any] = {
    "name": "clause_evidence",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "on_topic": {
                "type": "boolean",
                "description": "이 텍스트가 실제로 [조항 설명]과 같은 주제를 다루는가",
            },
            "quote": {
                "type": ["string", "null"],
                "description": (
                    "판단 근거가 되는 원문 문장 그대로 옮긴 것. 요약·의역 금지. "
                    "on_topic=false면 null"
                ),
            },
            "value_raw": {
                "type": ["string", "null"],
                "description": (
                    "수치형 규칙일 때만: 기간/비율 표현을 원문 그대로 담는다 "
                    "(예: '3년간', '100분의 50'). 숫자로 계산·변환하지 마라. "
                    "문언형 규칙이거나 해당 값이 없으면 null"
                ),
            },
            "ownership": {
                "type": ["string", "null"],
                "description": (
                    "문언형(권리 귀속) 규칙일 때만: "
                    "'발주기관단독' | '공동' | '계약상대자단독' | '불명확' 중 하나. "
                    "수치형 규칙이면 null"
                ),
            },
        },
        "required": ["on_topic", "quote", "value_raw", "ownership"],
    },
}

SYSTEM_PROMPT = """너는 RFP 조항 텍스트에서 특정 주제의 근거를 찾아 옮겨 적는 도구다. 규칙:
1. [조항 설명]과 실제로 같은 주제를 다루는 문장이 있을 때만 on_topic=true로 하라.
   비슷해 보여도 다른 주제(예: 다른 종류의 보증금, 다른 기간)면 false로 하라.
2. quote는 원문 문장을 그대로 옮긴다. 요약하거나 표현을 바꾸지 마라.
3. value_raw(수치 표현)는 원문 그대로 담는다. 계산하거나 숫자로 바꾸지 마라.
4. 판단(적절한지, 기준을 초과하는지 등)은 절대 하지 마라. 사실을 찾아 옮기기만 하라."""

FallbackResult = tuple[
    ClauseVerdict | None, str, dict[str, Any] | None, str | None, dict[str, Any] | None
]

_NOTHING_FOUND: FallbackResult = (None, "", None, None, None)


def _squash(text: str | None) -> str:
    return re.sub(r"\s+", "", text or "")


def quote_is_grounded(quote: str | None, chunk_text: str) -> bool:
    """Does the quoted sentence actually occur in the source? Hallucination gate."""
    if not quote:
        return False
    return _squash(quote)[:_QUOTE_PREFIX_CHARS] in _squash(chunk_text)


def _topic_brief(rule: dict[str, Any], resolved: dict[str, Any]) -> str:
    """Describe what to look for, including the standard clause text itself.

    Passing the standard clause matters. Given only a short label like "하자보수
    기간 과다", the model wavers on wording that shares no vocabulary with it.
    With the actual clause in front of it, what the text is being compared to is
    unambiguous and the answers stop drifting between runs.
    """
    topic = f"{rule['name']} — {resolved['desc']}"
    clause = resolved.get("clause")
    if clause and clause.get("text"):
        topic += f"\n\n표준 조항 원문({clause.get('title', '')}):\n{clause['text'][:500]}"
    return topic


def _gate_candidates(
    scored: list[tuple[dict[str, Any], float]],
    *,
    method: str,
    similarity_threshold: float,
    top_k: int,
) -> list[dict[str, Any]]:
    """Pick which chunks are worth a model call, according to how they were scored.

    The absolute threshold is calibrated against real embeddings. On the offline
    character-bigram fallback the score distribution is different enough that the
    same number is meaningless — measured against the real 예규 corpus, related
    clauses scored 0.096–0.364 while unrelated ones reached 0.162, so the two
    ranges overlap and no cut separates them.

    So the fallback ranks instead of thresholding. Cost stays bounded at `top_k`
    calls per unresolved rule, and the filters that actually matter are unchanged:
    the model still has to say the text is on topic, the quote still has to occur
    in the document, and the comparison is still done in code.
    """
    if method == "ngram":
        return [chunk for chunk, _score in scored[:top_k]]
    return [chunk for chunk, score in scored[:top_k] if score >= similarity_threshold]


def _extract_evidence(
    rule: dict[str, Any],
    resolved: dict[str, Any],
    chunk: dict[str, Any],
    structured_extract: StructuredExtractor,
) -> dict[str, Any] | None:
    user_body = (
        f"[조항 설명]\n{_topic_brief(rule, resolved)}\n\n"
        f"[검토할 텍스트]\n{(chunk.get('text') or '')[:2000]}"
    )
    try:
        extracted = structured_extract(SYSTEM_PROMPT, user_body, EVIDENCE_SCHEMA)
    except Exception:
        return None
    if not extracted.get("on_topic") or not extracted.get("quote"):
        return None
    if not quote_is_grounded(extracted["quote"], chunk.get("text") or ""):
        return None  # quoted something that is not in the document — discard
    return extracted


def make_embedding_fallback(
    structured_extract: StructuredExtractor,
    *,
    embed: Embedder | None = None,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
    top_k: int = TOP_K,
) -> Callable[..., FallbackResult]:
    """Build the tier-two finder that `detect_standard_diff` accepts."""

    def find_via_embedding(
        rule: dict[str, Any],
        resolved: dict[str, Any],
        chunks: list[dict[str, Any]],
        inspected_ids: set[str],
    ) -> FallbackResult:
        clause = resolved.get("clause") if resolved else None
        if not clause or resolved.get("status") != "ok":
            return _NOTHING_FOUND

        pool = [
            chunk
            for chunk in chunks
            if chunk.get("chunk_id") not in inspected_ids and (chunk.get("text") or "").strip()
        ]
        if not pool:
            return _NOTHING_FOUND

        query = f"{rule['name']} — {resolved['desc']}. {clause['text'][:300]}"
        try:
            matrix, method = similarity_matrix(
                [chunk.get("text") or "" for chunk in pool], [query], embed=embed
            )
        except Exception:
            return _NOTHING_FOUND

        scored = sorted(
            zip(pool, (row[0] for row in matrix)), key=lambda pair: -pair[1]
        )
        candidates = _gate_candidates(
            scored,
            method=method,
            similarity_threshold=similarity_threshold,
            top_k=top_k,
        )
        if not candidates:
            return _NOTHING_FOUND

        for chunk in candidates:
            evidence = _extract_evidence(rule, resolved, chunk, structured_extract)
            if evidence is None:
                continue

            if rule["direction"] == "text":
                ownership = evidence.get("ownership")
                if ownership == "발주기관단독":
                    return (
                        "NEEDS_REVIEW",
                        f"표준({resolved['desc']})과 다른 단독 귀속 문언(AI 보강 탐지)",
                        None,
                        evidence["quote"],
                        chunk,
                    )
                if ownership == "공동":
                    return (
                        "COMPLIANT",
                        "표준과 같은 공동소유 문언 확인(AI 보강 탐지)",
                        None,
                        evidence["quote"],
                        chunk,
                    )
                continue  # unclear on this chunk — try the next candidate

            value_raw = evidence.get("value_raw")
            if not value_raw:
                continue
            values = [
                value
                for value in extract_values(value_raw)
                if value["unit"] == resolved["unit"] and value.get("value") is not None
            ]
            if not values:
                continue
            found = values[0]
            minimum = rule.get("min_value_filter")
            if minimum is not None and found["value"] < minimum:
                continue

            # The same comparison tier one makes. Only the search differed.
            if found["value"] > resolved["value"] + 1e-4:
                return (
                    "NEEDS_REVIEW",
                    f"공고 값이 표준({resolved['desc']})을 초과(AI 보강 탐지)",
                    found,
                    evidence["quote"],
                    chunk,
                )
            return (
                "COMPLIANT",
                f"표준({resolved['desc']}) 이내(AI 보강 탐지)",
                found,
                evidence["quote"],
                chunk,
            )

        return _NOTHING_FOUND

    return find_via_embedding
