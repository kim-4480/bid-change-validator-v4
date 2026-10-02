"""Comparing a notice's contract terms against the published standard.

A clause in the notice is matched to the standard clause it corresponds to (by
sentence shape, then by embedding similarity), and the figures are compared **in
code**. The model is never asked whether a term is acceptable.

**No threshold is written in this file.** 하자보수 1년, 지체상금 상한 100분의 30 and the
rest are read from the rule text by `standards.values` on every run. What stays
here is only "which clause of the notice does this rule apply to". When the rules
are amended, rebuilding the clause index moves the thresholds with them; when a
threshold cannot be read, the rule reports UNDETERMINED rather than judging on a
stale constant.

Clause identification is by composed vocabulary parts, not fixed strings. The
warranty rule looks for [하자|결함|불량] + [보수|담보|책임], so "하자담보책임기간" and
"결함을 보수하여야" are both recognised as the same clause.

Known gap, reported rather than hidden: the liquidated-damages *rate* has no rule
yet — only the cap (제18조제1항) is judged. 용역계약일반조건 제55조 delegates the rate to
시행규칙 제75조, whose text is indexed, so what remains is adding the rule.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from bidengine.normalization import extract_values
from bidengine.providers.embeddings import Embedder, similarity_matrix
from bidengine.clause_review.contracts import (
    CATEGORY_BY_RULE,
    VERDICT_PRIORITY,
    ClauseFinding,
    ClauseVerdict,
    StandardReference,
    excerpt,
)
from bidengine.clause_review.lexicon import (
    AUTHORITY_RE,
    BEAR_VERB_RE,
    DAMAGE_NOUN_RE,
    DECREASE_RE,
    DEFECT_NOUN,
    DELAY_PENALTY_RE,
    FAULT_CARVE_OUT_RE,
    INSPECTION_RE,
    IP_NOUN_RE,
    JOINT_OWNERSHIP_RE,
    NO_FAULT_LIABILITY_RE,
    PAYMENT_NOUN_RE,
    PAYMENT_VERB_RE,
    PRODUCT_RE,
    SOLE_VERB_RE,
    TERMINATION_RE,
)
from bidengine.clause_review.standards.values import resolve_all


_GAP = r"[^.\n]{0,30}?"
_SGAP = r"[^.\n]{0,15}?"

# Which chapter of 용역계약일반조건 governs this notice. 하자담보 and 지식재산권 are
# stated per chapter, so reviewing a 물품 notice against the 소프트웨어용역 chapter
# reports a departure from a standard that never applied to it.
#
# Read off the notice's own words rather than a field, because the list API's
# business-type code is not carried on the chunks and is often absent anyway.
_SOFTWARE_SCOPE_RE = re.compile(
    r"소프트웨어|SW\b|정보화|정보시스템|시스템\s*(?:구축|개발|고도화)|"
    r"응용\s*프로그램|플랫폼\s*구축|홈페이지|웹\s*사이트|앱\s*개발",
    re.IGNORECASE,
)
_CM_SCOPE_RE = re.compile(r"건설사업관리|시공\s*단계의\s*건설사업관리|CM\s*용역")

# 나라장터's own business type settles which 계약예규 governs, so when a notice
# carries one there is nothing to infer. Only 용역 needs the prose read, because
# 소프트웨어용역 and 건설사업관리 are chapters inside it rather than types of their own.
SCOPE_BY_BUSINESS_TYPE = {
    "GOODS": "GOODS",
    "CONSTRUCTION": "CONSTRUCTION",
    "SERVICE": None,
    "FOREIGN": None,
    "OTHER": None,
}


def scope_for_notice(
    chunks: list[dict[str, Any]], *, business_type: str | None = None
) -> str:
    """The rules this notice should be measured against.

    Prefers 나라장터's business type and reads the prose only when that leaves the
    question open.
    """
    if business_type:
        settled = SCOPE_BY_BUSINESS_TYPE.get(business_type)
        if settled:
            return settled
    return infer_contract_scope(chunks)

# One mention proves nothing — a 물품 notice may name a system it plugs into.
# Requiring several keeps an incidental reference from switching the standard.
_SCOPE_MIN_HITS = 3


def infer_contract_scope(chunks: list[dict[str, Any]]) -> str:
    """Which chapter's terms this notice should be measured against.

    Falls back to "COMMON", the chapter that governs every 용역 contract. That
    default is the safe one: rules stated only for a narrower chapter withhold
    their verdict instead of applying a standard the contract never had.
    """
    text = "\n".join(chunk.get("text") or "" for chunk in chunks)
    if len(_CM_SCOPE_RE.findall(text)) >= _SCOPE_MIN_HITS:
        return "CM"
    if len(_SOFTWARE_SCOPE_RE.findall(text)) >= _SCOPE_MIN_HITS:
        return "SOFTWARE"
    return "COMMON"

# Rules identify *which clause of the notice* a comparison applies to. The value
# compared against comes from the rule text, never from here.
#
# match            : shape regex identifying the clause
# require          : must also be present, or it is a different clause
# sentence_exclude : present in the same sentence means this rule does not apply
#                    (stops a figure being attributed to the wrong rule)
# direction        : "gt" numeric comparison | "text" wording comparison
RULES: list[dict[str, Any]] = [
    {
        "id": "warranty_period",
        "name": "하자보수 기간 과다",
        "direction": "gt",
        "match": rf"{DEFECT_NOUN}{_SGAP}(?:보수|담보|책임|수정)"
        rf"|무상\s*(?:유지\s*)?(?:보수|관리)"
        rf"|무상으?로?{_SGAP}(?:보수|수정)",
        # The warranty *bond rate* is a separate rule; same sentence means this
        # figure belongs to that one, not to the warranty period.
        "sentence_exclude": r"보증금|이행보증",
    },
    {
        "id": "warranty_bond_rate",
        "name": "하자보수보증금율 과다",
        "direction": "gt",
        "match": rf"{DEFECT_NOUN}[^.\n]{{0,12}}?(?:보증금|이행보증)",
    },
    {
        "id": "ip_ownership",
        "name": "저작권(지식재산권) 귀속",
        "direction": "text",
        "match": rf"(?:{IP_NOUN_RE}|{PRODUCT_RE})",
        # Sole vesting: [right|deliverable] … [authority] … [vest|own|transfer]
        "text_forms": [
            rf"(?:{IP_NOUN_RE}|{PRODUCT_RE}){_GAP}{AUTHORITY_RE}{_SGAP}{SOLE_VERB_RE}",
            rf"{AUTHORITY_RE}{_GAP}(?:{IP_NOUN_RE}|{PRODUCT_RE}){_SGAP}{SOLE_VERB_RE}",
        ],
        "text_ok": JOINT_OWNERSHIP_RE,
    },
    {
        "id": "penalty_cap",
        "name": "지체상금 상한 초과",
        "direction": "gt",
        "match": DELAY_PENALTY_RE,
        # The daily *rate* is a fraction of a percent and is judged by
        # `penalty_rate`; only the ceiling belongs to this rule.
        "min_value_filter": 5,
    },
    {
        "id": "penalty_rate",
        "name": "지체상금 요율 과다",
        "direction": "gt",
        "match": DELAY_PENALTY_RE,
        # The ceiling is tens of percent; the rate never is.
        "max_value_filter": 5,
    },
    {
        "id": "inspection_period",
        "name": "검수 기간 과다",
        "direction": "gt",
        "match": INSPECTION_RE,
        # Stops "하자담보책임기간은 검수완료일로부터 36개월" donating its figure here.
        # 대가/기성 too: "검사완료일부터 5일 이내에 기성대가를 지급" is a payment
        # deadline that happens to name an inspection, and belongs to that rule.
        "sentence_exclude": r"하자|결함|무상|담보|유지\s*(?:보수|관리)|대가|대금|기성",
    },
    {
        "id": "termination_threshold",
        "name": "계약금액 감소로 인한 해지 요건 강화",
        "direction": "gt",
        "match": TERMINATION_RE,
        "require": DECREASE_RE,
    },
    {
        "id": "payment_period",
        "name": "대금지급 기한 과다",
        "direction": "gt",
        "match": rf"{PAYMENT_NOUN_RE}{_GAP}{PAYMENT_VERB_RE}"
        rf"|{PAYMENT_VERB_RE}{_SGAP}(?:기한|기일|기간)",
        # Days in these sentences count something else entirely: how late delivery
        # is penalised, how long a defect is covered, when work must start.
        "sentence_exclude": r"지체\s*상금|지연\s*배상|하자|결함|착수|준공\s*기한|보증금",
    },
    {
        "id": "liability_scope",
        "name": "손해배상 범위 과다",
        "direction": "text",
        "match": rf"{DAMAGE_NOUN_RE}{_GAP}{BEAR_VERB_RE}",
        # The risky shape is liability detached from fault, or reaching everything.
        "text_forms": [
            rf"{NO_FAULT_LIABILITY_RE}{_GAP}{BEAR_VERB_RE}",
            rf"{DAMAGE_NOUN_RE}{_GAP}{NO_FAULT_LIABILITY_RE}",
            rf"{NO_FAULT_LIABILITY_RE}{_GAP}{DAMAGE_NOUN_RE}",
        ],
        "text_ok": FAULT_CARVE_OUT_RE,
        "text_flag_reason": "표준({desc})과 달리 귀책 여부를 따지지 않는 배상 문언",
        "text_ok_reason": "표준과 같이 책임 없는 손해를 발주기관 부담으로 둔 문언 확인",
        "text_undetermined_reason": (
            "손해 관련 조항은 있으나 책임 범위 문언을 확정하지 못함 — 담당자 확인 필요"
        ),
        # 지체상금 is its own capped remedy, and insurance clauses allocate risk
        # rather than widen liability.
        "sentence_exclude": r"지체\s*상금|지연\s*배상|보험",
    },
]

for _rule in RULES:
    _rule["_match_re"] = re.compile(_rule["match"])
    _rule["_require_re"] = re.compile(_rule["require"]) if _rule.get("require") else None
    _rule["_exclude_re"] = (
        re.compile(_rule["sentence_exclude"]) if _rule.get("sentence_exclude") else None
    )
    _rule["_ok_re"] = re.compile(_rule["text_ok"]) if _rule.get("text_ok") else None
    _rule["_form_res"] = [re.compile(form) for form in _rule.get("text_forms", [])]

RULES_BY_ID = {rule["id"]: rule for rule in RULES}

# Minimum similarity for a shape-matched chunk to be treated as the right one.
SIMILARITY_THRESHOLD = 0.15

# Sentence break: after a terminal ending, or at a line break.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=다\.)\s*|(?<=함\.)\s*|(?<=음\.)\s*|\n")

# A fallback search for clauses the regexes did not find. It returns
# (verdict, reason, value, quote, chunk) or a verdict of None when it finds
# nothing. Injected so this module stays free of model and network calls.
EmbeddingFallback = Callable[
    [dict[str, Any], dict[str, Any], list[dict[str, Any]], set[str]],
    tuple[ClauseVerdict | None, str, dict[str, Any] | None, str | None, dict[str, Any] | None],
]


def _sentence_applies(rule: dict[str, Any], sentence: str) -> bool:
    if not rule["_match_re"].search(sentence):
        return False
    if rule["_require_re"] and not rule["_require_re"].search(sentence):
        return False
    if rule["_exclude_re"] and rule["_exclude_re"].search(sentence):
        return False
    return True


def _relevant_sentences(rule: dict[str, Any], text: str) -> list[str]:
    """Only the sentences this rule applies to.

    Narrowing to sentences is what stops an unrelated figure elsewhere in the
    same chunk being read as this clause's value.
    """
    return [
        sentence
        for sentence in _SENTENCE_SPLIT_RE.split(text or "")
        if sentence and _sentence_applies(rule, sentence)
    ]


# How far from the clause's own wording a figure may sit and still be its own.
# A real clause keeps the two close ("인수 확인 후 36개월간 하자보수 책임"); a
# 제안서 목차 line runs hundreds of characters with no sentence break, so a
# "최근 3년간 수행실적" entry can end up in the same span as a "하자보수 계획" entry
# and be read as a warranty period. Bounding the distance separates them.
VALUE_WINDOW_CHARS = 80


def _windows_around_match(rule: dict[str, Any], sentence: str) -> str:
    """The parts of a sentence close enough to this rule's wording to belong to it."""
    windows: list[str] = []
    for match in rule["_match_re"].finditer(sentence):
        start = max(0, match.start() - VALUE_WINDOW_CHARS)
        end = min(len(sentence), match.end() + VALUE_WINDOW_CHARS)
        windows.append(sentence[start:end])
    return " ".join(windows) if windows else sentence


def _candidate_chunks(
    rule: dict[str, Any], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [chunk for chunk in chunks if _relevant_sentences(rule, chunk.get("text") or "")]


def _standard_reference(resolved: dict[str, Any] | None) -> StandardReference | None:
    if resolved is None:
        return None
    clause = resolved.get("clause")
    return StandardReference(
        source=clause["source"] if clause else None,
        clause_ref=resolved.get("ref"),
        description=resolved.get("desc"),
        value=resolved.get("value"),
        value_raw=resolved.get("raw"),
        unit=resolved.get("unit"),
        note=resolved.get("notes") or None,
        text_excerpt=excerpt(clause["text"], 250) if clause else None,
        chapter=clause.get("chapter") if clause else None,
    )


def _finding(
    rule: dict[str, Any],
    resolved: dict[str, Any] | None,
    chunk: dict[str, Any] | None,
    verdict: ClauseVerdict,
    reason: str,
    *,
    value: dict[str, Any] | None = None,
    matched_text: str | None = None,
    matched_via: str = "REGEX",
    notice_version_id: str | None = None,
) -> ClauseFinding:
    category = CATEGORY_BY_RULE[rule["id"]]
    return ClauseFinding(
        rule_id=rule["id"],
        risk_type=rule["name"],
        category=category,
        label=rule["name"],
        detection_method="STANDARD_DIFF",
        matched_via=matched_via,  # type: ignore[arg-type]
        verdict=verdict,
        reason=reason,
        matched_text=matched_text,
        notice_version_id=notice_version_id,
        chunk_id=chunk.get("chunk_id") if chunk else None,
        clause_label=chunk.get("clause_label") if chunk else None,
        excerpt=excerpt(chunk.get("text")) if chunk else None,
        notice_value=value.get("value") if value else None,
        notice_value_raw=value.get("raw") if value else None,
        notice_value_unit=value.get("unit") if value else None,
        standard=_standard_reference(resolved),
        details={"drift": resolved.get("drift")} if resolved and resolved.get("drift") else {},
    )


def _judge_numeric(
    rule: dict[str, Any], resolved: dict[str, Any], chunk: dict[str, Any]
) -> tuple[ClauseVerdict | None, str, dict[str, Any] | None]:
    """Compare the figure in the notice against the one read from the rules.

    A verdict of None means this chunk is not this rule's business at all, which
    is different from being unable to decide.
    """
    sentences = _relevant_sentences(rule, chunk.get("text") or "")
    if not sentences:
        return (None, "규칙 형식에 맞는 문장 없음 — 판정 대상 아님", None)

    scope = " ".join(_windows_around_match(rule, sentence) for sentence in sentences)
    values = [
        value for value in extract_values(scope) if value["unit"] == resolved["unit"]
    ]
    # 지체상금 states both figures in one breath — "1일당 0.5%로 하며, 총액은 100분의
    # 30을 초과하지 아니한다" — so the two rules split that sentence by magnitude:
    # the cap takes the large figure, the rate the small one.
    minimum = rule.get("min_value_filter")
    if minimum is not None:
        values = [
            value
            for value in values
            if value["value"] is None or value["value"] >= minimum
        ]
    maximum = rule.get("max_value_filter")
    if maximum is not None:
        values = [
            value
            for value in values
            if value["value"] is None or value["value"] <= maximum
        ]
    if not values:
        return ("UNDETERMINED", "관련 조항은 있으나 수치 정규화 실패 — 담당자 확인 필요", None)

    worst = max(values, key=lambda value: value["value"] if value["value"] is not None else -1)
    if worst["value"] is None:
        return ("UNDETERMINED", "수치 정규화 실패 — 담당자 확인 필요", None)

    # Float tolerance: 14일 normalizes to 0.4667 months against a 14/30 standard.
    if worst["value"] > resolved["value"] + 1e-4:
        return ("NEEDS_REVIEW", f"공고 값이 표준({resolved['desc']})을 초과", worst)
    return ("COMPLIANT", f"표준({resolved['desc']}) 이내", worst)


def _judge_text(
    rule: dict[str, Any], resolved: dict[str, Any], chunk: dict[str, Any]
) -> tuple[ClauseVerdict | None, str, dict[str, Any] | None, str | None]:
    """Wording rules are judged sentence by sentence.

    One chunk can hold both a compliant joint-ownership sentence and a
    sole-vesting one, so checking the chunk as a whole would let either hide the
    other.
    """
    sentences = _relevant_sentences(rule, chunk.get("text") or "")
    if not sentences:
        return (None, "규칙 형식에 맞는 문장 없음 — 판정 대상 아님", None, None)

    # A proviso often carries the standard wording in a sentence of its own —
    # "…손해를 부담한다. 다만, 책임없는 사유로 발생한 경우에는 발주기관이 부담한다." —
    # and that second sentence need not name the harm again, so it is not one of
    # the rule's own sentences. The chunk is therefore scanned as a whole for the
    # standard wording, while violations are still found sentence by sentence.
    saw_standard_wording = bool(
        rule["_ok_re"] and rule["_ok_re"].search(chunk.get("text") or "")
    )
    for sentence in sentences:
        if rule["_ok_re"] and rule["_ok_re"].search(sentence):
            saw_standard_wording = True
            continue
        for form in rule["_form_res"]:
            match = form.search(sentence)
            if match:
                template = rule.get("text_flag_reason", "표준({desc})과 다른 단독 귀속 문언")
                return (
                    "NEEDS_REVIEW",
                    template.format(desc=resolved["desc"]),
                    None,
                    match.group(0).strip(),
                )
    if saw_standard_wording:
        return (
            "COMPLIANT",
            rule.get("text_ok_reason", "표준과 같은 공동소유·지분균등 문언 확인"),
            None,
            None,
        )
    return (
        "UNDETERMINED",
        rule.get(
            "text_undetermined_reason",
            "관련 조항은 있으나 귀속 방식 문언을 확정하지 못함 — 담당자 확인 필요",
        ),
        None,
        None,
    )


def _most_relevant_chunks(
    candidates: list[dict[str, Any]],
    standard_clause: dict[str, Any] | None,
    *,
    embed: Embedder | None,
) -> list[dict[str, Any]]:
    """Narrow shape-matched candidates to the ones closest to the standard clause."""
    if not standard_clause or len(candidates) <= 1:
        return candidates
    try:
        matrix, _method = similarity_matrix(
            [chunk.get("text") or "" for chunk in candidates],
            [standard_clause["text"]],
            embed=embed,
        )
    except Exception:
        return candidates  # similarity is an optimisation, never a gate

    scored = sorted(
        zip(candidates, (row[0] for row in matrix)), key=lambda pair: -pair[1]
    )
    return [chunk for chunk, score in scored if score >= SIMILARITY_THRESHOLD] or [
        scored[0][0]
    ]


def detect_standard_diff(
    chunks: list[dict[str, Any]],
    clauses: list[dict[str, Any]],
    *,
    notice_version_id: str | None = None,
    contract_scope: str | None = None,
    embed: Embedder | None = None,
    embedding_fallback: EmbeddingFallback | None = None,
) -> list[ClauseFinding]:
    """Run path A. Returns one finding per rule, COMPLIANT verdicts included.

    Two tiers:

    1. Regex and lexicon — immediate and free. Known wording ends here.
    2. Only when tier 1 reached no confident verdict (found nothing, or only
       UNDETERMINED), the injected `embedding_fallback` searches the chunks the
       regexes did not look at. The comparison logic is identical; only the way
       the source sentence is located differs, which is what catches wording the
       lexicon has never seen ("품질을 보장하며 자비로 해결").

    That ordering is the cost control: a rule that already has a confident answer
    never triggers tier 2, so at worst the extra calls equal the number of rules
    that came back unresolved.

    `contract_scope` selects which chapter of the rules governs; when omitted it
    is read off the notice. A rule the chapter says nothing about produces no
    finding at all — silence, rather than a verdict against a standard that never
    applied to this contract.
    """
    scope = contract_scope or infer_contract_scope(chunks)
    standards = resolve_all(clauses, contract_scope=scope)
    findings: list[ClauseFinding] = []

    for rule in RULES:
        resolved = standards[rule["id"]]

        if resolved["status"] == "out_of_scope":
            continue

        if resolved["status"] != "ok":
            # The threshold could not be read from the rule text. Judging on a
            # constant hard-coded here would be confidently wrong, so this rule
            # withholds its verdict and says why.
            findings.append(
                _finding(
                    rule,
                    resolved,
                    None,
                    "UNDETERMINED",
                    f"표준 기준값을 예규 원문에서 확인하지 못해 판정 보류 "
                    f"({resolved['status']}) — {resolved['notes']}",
                    matched_via="STANDARD_UNRESOLVED",
                    notice_version_id=notice_version_id,
                )
            )
            continue

        candidates = _candidate_chunks(rule, chunks)
        inspected_ids = {chunk.get("chunk_id") for chunk in candidates}
        rule_findings: list[ClauseFinding] = []

        for chunk in _most_relevant_chunks(candidates, resolved["clause"], embed=embed):
            matched_text = None
            if rule["direction"] == "text":
                verdict, reason, value, matched_text = _judge_text(rule, resolved, chunk)
            else:
                verdict, reason, value = _judge_numeric(rule, resolved, chunk)
            if verdict is None:
                continue
            rule_findings.append(
                _finding(
                    rule,
                    resolved,
                    chunk,
                    verdict,
                    reason,
                    value=value,
                    matched_text=matched_text,
                    notice_version_id=notice_version_id,
                )
            )

        rule_findings.sort(key=lambda finding: VERDICT_PRIORITY[finding.verdict])
        best = rule_findings[0] if rule_findings else None

        if embedding_fallback is not None and (best is None or best.verdict == "UNDETERMINED"):
            verdict, reason, value, quote, chunk = embedding_fallback(
                rule, resolved, chunks, inspected_ids
            )
            if verdict is not None:
                fallback = _finding(
                    rule,
                    resolved,
                    chunk,
                    verdict,
                    reason,
                    value=value,
                    matched_text=quote,
                    matched_via="EMBEDDING_LLM",
                    notice_version_id=notice_version_id,
                )
                # When both tiers are UNDETERMINED the regex reason is kept: it is
                # anchored closer to the standard clause.
                if best is None or VERDICT_PRIORITY[verdict] < VERDICT_PRIORITY[best.verdict]:
                    best = fallback

        if best is not None:
            findings.append(best)

    return findings
