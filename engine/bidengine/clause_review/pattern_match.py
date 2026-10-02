"""Pattern detection for risks that have no standard figure to compare against.

An open-ended scope clause is not "a value above the standard" — the government
contract rules state no number for it. The problem is the *shape* of the sentence:
it leaves the scope of work permanently open, so the bidder cannot price it and
cannot tell when the work is finished.

So this path never consults the standard corpus and never retrieves anything. It
composes patterns from the vocabulary parts in `lexicon.py`:

    a catch-all clause is [residual][authority][discretion verb][open object]

Adding one synonym to a part widens every shape that uses it.
"""

from __future__ import annotations

import re
from typing import Any

from bidengine.clause_review.contracts import CATEGORY_BY_RULE, ClauseFinding, excerpt
from bidengine.clause_review.lexicon import (
    ANCILLARY_RE,
    AUTHORITY_RE,
    DEFERRAL_RE,
    DEFERRAL_VERB,
    DISCRETION_RE,
    OPEN_OBJECT_RE,
    RESIDUAL_RE,
    SCOPE_OBJECT_RE,
)


RULE_ID = "open_ended_scope"
RISK_TYPE = "과업범위 모호(포괄조항)"

# How much qualifying text may sit between two parts of one shape.
_GAP = r"[^.\n]{0,30}?"
_SGAP = r"[^.\n]{0,15}?"

# (shape name, pattern, why it matters, needs work-scope context)
_FORMS: list[tuple[str, str, str, bool]] = [
    (
        "잔여지시어+재량동사+열린대상",
        rf"{RESIDUAL_RE}{_GAP}{DISCRETION_RE}{_SGAP}{OPEN_OBJECT_RE}",
        "과업 범위를 무한정 확장하는 포괄조항",
        False,
    ),
    (
        "재량주체+필요인정",
        rf"{AUTHORITY_RE}{_SGAP}필요하다고\s*인정(?:하는|하여|되는|하면)",
        "발주기관 재량으로 범위가 열리는 포괄조항",
        False,
    ),
    (
        "부수·수반 표현",
        rf"{ANCILLARY_RE}(?:되는|하는|적인|된)\s*{_SGAP}(?:일체|모든|제반|전부)?\s*{OPEN_OBJECT_RE}",
        "'부수·수반되는 일체' 형식 — 범위를 닫지 않는 포괄 표현",
        True,
    ),
    (
        # The object is narrowed to scope nouns here. Legal boilerplate such as
        # "손해배상 등 일체의 민·형사상 책임" is not a scope-of-work clause.
        "열거 뒤 확장",
        rf"등\s*(?:에\s*관한|의|을\s*포함(?:한|하여|하는)|과\s*관련된)?\s*"
        rf"(?:일체의?\s*|모든\s*|제반\s*)?{SCOPE_OBJECT_RE}",
        "열거 뒤 무한 확장 표현",
        True,
    ),
    (
        "미확정 위임",
        rf"{DEFERRAL_RE}{_SGAP}{DEFERRAL_VERB}",
        "범위 미확정 — 협의·추후 결정 위임 조항",
        True,
    ),
]

_COMPILED = [
    (name, re.compile(pattern), reason, guarded)
    for name, pattern, reason, guarded in _FORMS
]

# Some shapes are common in statutes and ordinary prose, so they only count
# inside a passage that is actually about the work to be performed.
_SCOPE_CONTEXT_KEYWORDS = ("과업", "업무", "수행", "요구사항", "산출물", "용역", "사업")

# Attachment forms and registers are not scope clauses; they only look like them.
_FORM_MARKER_RE = re.compile(
    r"별지\s*서식|관리대장|\(인\)\s*$|서명\s*\d|년\s*월\s*일\s*확인자", re.MULTILINE
)


def detect_patterns(
    chunks: list[dict[str, Any]],
    *,
    notice_version_id: str | None = None,
) -> list[ClauseFinding]:
    """Run the pattern path. At most one finding per shape per chunk."""
    findings: list[ClauseFinding] = []

    for chunk in chunks:
        text = chunk.get("text") or ""
        if _FORM_MARKER_RE.search(text):
            continue
        has_scope_context = any(keyword in text for keyword in _SCOPE_CONTEXT_KEYWORDS)
        seen_spans: list[tuple[int, int]] = []

        for name, pattern, reason, guarded in _COMPILED:
            match = pattern.search(text)
            if not match:
                continue
            if guarded and not has_scope_context:
                continue
            # Two shapes firing on the same span is one problem, not two.
            if any(
                not (match.end() <= start or match.start() >= end)
                for start, end in seen_spans
            ):
                continue
            seen_spans.append((match.start(), match.end()))

            findings.append(
                ClauseFinding(
                    rule_id=RULE_ID,
                    risk_type=RISK_TYPE,
                    category=CATEGORY_BY_RULE["open_ended_scope"],
                    label=RISK_TYPE,
                    detection_method="PATTERN_MATCH",
                    matched_via="REGEX",
                    verdict="NEEDS_REVIEW",
                    reason=reason,
                    form=name,
                    matched_text=match.group(0).strip(),
                    notice_version_id=notice_version_id,
                    chunk_id=chunk.get("chunk_id"),
                    clause_label=chunk.get("clause_label"),
                    excerpt=excerpt(text),
                    # This risk has no counterpart figure in the standard rules,
                    # which is precisely why it needs the pattern path.
                    standard=None,
                )
            )

    return findings
