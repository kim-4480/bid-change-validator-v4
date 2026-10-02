"""Deterministic numeric normalization copied from the existing LLM/RAG PoC.

Principles:
- Preserve the raw source string.
- Never ask the LLM to convert numbers.
- Failed parses stay explicit instead of being guessed.
- Periods are normalized to months.
"""

from __future__ import annotations

import re

COMPARATORS = {
    "이상": ">=",
    "초과": ">",
    "이하": "<=",
    "미만": "<",
    "이내": "<=",
    "이후": ">=",
}

PERIOD_UNITS = {"년": 12, "개월": 1, "월": 1, "주": 0.25, "일": 1 / 30}

_HANGUL_DIGITS = {
    "영": 0,
    "공": 0,
    "일": 1,
    "이": 2,
    "삼": 3,
    "사": 4,
    "오": 5,
    "육": 6,
    "륙": 6,
    "칠": 7,
    "팔": 8,
    "구": 9,
}
_SMALL_MULT = {"십": 10, "백": 100, "천": 1000}
_GROUP_UNITS = {"만": 10**4, "억": 10**8, "조": 10**12}

_NUM_TOKEN_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)"
    r"|([영공일이삼사오육륙칠팔구])"
    r"|([십백천])"
    r"|([만억조])"
)

_AMOUNT_RE = re.compile(
    r"(?:금\s*)?"
    r"((?:[\d,\.]|[영공일이삼사오육륙칠팔구십백천만억조]|\s)+?)\s*원(?:정)?"
)
_OP_RE = re.compile("|".join(COMPARATORS.keys()))
_PERIOD_RE = re.compile(r"(\d+(?:\.\d+)?|[영공일이삼사오육륙칠팔구십백천]+)\s*(년|개월|월|주|일)")
_PERCENT_BUNUI_RE = re.compile(
    r"(\d+(?:\.\d+)?|[일이삼사오육륙칠팔구십백천]+)\s*분의\s*"
    r"(\d+(?:\.\d+)?|[일이삼사오육륙칠팔구십백천]+)"
)
# Contract schedules commonly write rates as `1/1,000` instead of `1천분의 1`.
# The numerator comes first in this notation.
_PERCENT_SLASH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d[\d,]*(?:\.\d+)?)")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|퍼센트|프로|퍼)")
_COUNT_RE = re.compile(r"(\d+|[일이삼사오육륙칠팔구십]+)\s*(?:명|인(?![근시])|인원)")


def parse_korean_number(text: str | None):
    if not text:
        return None

    total = 0.0
    section = 0.0
    number = None
    matched_any = False

    for match in _NUM_TOKEN_RE.finditer(text):
        arabic, hangul_digit, small, group = match.groups()
        matched_any = True

        if arabic is not None:
            number = float(arabic.replace(",", ""))
        elif hangul_digit is not None:
            digit = float(_HANGUL_DIGITS[hangul_digit])
            if number is not None and number == int(number) and number < 10:
                number = number * 10 + digit
            else:
                number = digit
        elif small is not None:
            section += (number if number is not None else 1) * _SMALL_MULT[small]
            number = None
        elif group is not None:
            section += number if number is not None else 0
            if section == 0:
                section = 1
            total += section * _GROUP_UNITS[group]
            section = 0.0
            number = None

    if not matched_any:
        return None

    total += section + (number if number is not None else 0)
    return int(total) if total == int(total) else total


def _find_op(text: str, after_pos: int = 0):
    best = None
    for keyword, operator in COMPARATORS.items():
        index = text.find(keyword, after_pos)
        if index >= 0 and (best is None or index < best[0]):
            best = (index, keyword, operator)
    return (best[2], best[1]) if best else (None, None)


def _failed(raw: str | None, unit: str | None = None, reason: str = ""):
    return {
        "raw": raw,
        "value": None,
        "unit": unit,
        "op": None,
        "parse_status": "failed",
        "parse_notes": reason or "수치 해석 불가",
    }


def normalize_amount(raw: str):
    if not raw or not raw.strip():
        return _failed(raw, "KRW", "빈 문자열")

    text = raw.strip()
    found = []
    body = re.sub(r"\([^)]*\)", " ", text)

    for match in _AMOUNT_RE.finditer(body):
        value = parse_korean_number(match.group(1))
        if value is None:
            continue
        tail = body[match.end():]
        op_match = _OP_RE.match(tail.lstrip())
        operator = COMPARATORS[op_match.group(0)] if op_match else None
        found.append((value, operator))

    if not found:
        return _failed(raw, "KRW", "금액 표현을 찾지 못함")

    if len(found) == 1:
        value, operator = found[0]
        return {
            "raw": raw,
            "value": value,
            "unit": "KRW",
            "op": operator,
            "parse_status": "success",
            "parse_notes": "",
        }

    lows = [(value, op) for value, op in found if op in (">=", ">")]
    highs = [(value, op) for value, op in found if op in ("<=", "<")]
    if lows and highs:
        return {
            "raw": raw,
            "value": None,
            "unit": "KRW",
            "op": None,
            "range": {
                "min": lows[0][0],
                "min_op": lows[0][1],
                "max": highs[0][0],
                "max_op": highs[0][1],
            },
            "parse_status": "success",
            "parse_notes": "",
        }

    return _failed(raw, "KRW", "복수 금액이 있으나 범위로 해석 불가")


def normalize_period(raw: str):
    if not raw or not raw.strip():
        return _failed(raw, "MONTH", "빈 문자열")

    text = raw.strip()
    match = _PERIOD_RE.search(text)
    if not match:
        return _failed(raw, "MONTH", "기간 표현을 찾지 못함")

    number_text, unit = match.groups()
    if re.match(r"^[\d.]+$", number_text):
        value = float(number_text)
    else:
        value = parse_korean_number(number_text)
        if value is None:
            return _failed(raw, "MONTH", "기간 수치 해석 불가")

    months = value * PERIOD_UNITS[unit]
    operator, _ = _find_op(text, match.end())
    return {
        "raw": raw,
        "value": round(months, 4),
        "unit": "MONTH",
        "op": operator,
        "parse_status": "success",
        "parse_notes": "",
        "orig_value": value,
        "orig_unit": unit,
    }


def normalize_percent(raw: str):
    if not raw or not raw.strip():
        return _failed(raw, "PERCENT", "빈 문자열")

    text = raw.strip()
    match = _PERCENT_BUNUI_RE.search(text)
    value = None
    end = 0

    if match:
        denominator_text, numerator_text = match.groups()
        denominator = (
            float(denominator_text)
            if re.match(r"^[\d.]+$", denominator_text)
            else parse_korean_number(denominator_text)
        )
        numerator = (
            float(numerator_text)
            if re.match(r"^[\d.]+$", numerator_text)
            else parse_korean_number(numerator_text)
        )
        if denominator and numerator is not None:
            value = numerator / denominator * 100
            end = match.end()

    if value is None:
        slash_match = _PERCENT_SLASH_RE.search(text)
        if slash_match:
            numerator = float(slash_match.group(1))
            denominator = float(slash_match.group(2).replace(",", ""))
            if denominator:
                value = numerator / denominator * 100
                end = slash_match.end()

    if value is None:
        percent_match = _PERCENT_RE.search(text)
        if percent_match:
            value = float(percent_match.group(1))
            end = percent_match.end()

    if value is None:
        return _failed(raw, "PERCENT", "백분율 표현을 찾지 못함")

    operator, _ = _find_op(text, end)
    value = int(value) if value == int(value) else value
    return {
        "raw": raw,
        "value": value,
        "unit": "PERCENT",
        "op": operator,
        "parse_status": "success",
        "parse_notes": "",
    }


def normalize_count(raw: str):
    if not raw or not raw.strip():
        return _failed(raw, "PERSON", "빈 문자열")

    text = raw.strip()
    match = _COUNT_RE.search(text)
    if not match:
        return _failed(raw, "PERSON", "인원 표현을 찾지 못함")

    number_text = match.group(1)
    if number_text.isdigit():
        value = int(number_text)
    else:
        value = parse_korean_number(number_text)
        if value is None:
            return _failed(raw, "PERSON", "인원 수치 해석 불가")

    operator, _ = _find_op(text, match.end())
    return {
        "raw": raw,
        "value": int(value),
        "unit": "PERSON",
        "op": operator,
        "parse_status": "success",
        "parse_notes": "",
    }


def normalize_value(raw: str):
    if not raw or not raw.strip():
        return _failed(raw, None, "빈 문자열")

    text = raw.strip()
    if (
        _PERCENT_BUNUI_RE.search(text)
        or _PERCENT_SLASH_RE.search(text)
        or _PERCENT_RE.search(text)
    ):
        return normalize_percent(text)
    if "원" in text and _AMOUNT_RE.search(re.sub(r"\([^)]*\)", " ", text)):
        return normalize_amount(text)
    if _PERIOD_RE.search(text):
        return normalize_period(text)
    if _COUNT_RE.search(text):
        return normalize_count(text)
    return _failed(raw, None, "금액/기간/백분율/인원 어느 것에도 해당하지 않음")


# NOTE(LLM/RAG 이식): clause_review(계약조항 검토)가 조항 텍스트에서 금액·기간·비율을
# 한꺼번에 뽑아내야 해서 추가했습니다. normalize_value()는 '이 문자열 하나가 얼마인가'를
# 답하지만, 조항 검토는 '이 문장에 어떤 수치들이 들어 있는가'라는 반대 질문이 필요합니다.
# 기존 함수·동작은 건드리지 않았습니다.
def extract_values(text: str | None) -> list[dict]:
    """Find every amount, period and percentage expression in free text.

    `normalize_value` answers "what is this one string worth"; clause review
    needs the opposite question — "what numbers does this clause contain" —
    because a clause states its own figure in the middle of a sentence.

    Each result carries a `context` window so a caller can show where the number
    came from. Expressions that fail to normalize are dropped rather than
    reported with a guessed value.
    """
    results: list[dict] = []
    if not text:
        return results

    def _context(start: int, end: int, before: int) -> str:
        return text[max(0, start - before) : min(len(text), end + 10)]

    # A trailing window is appended to each match so the comparator that follows
    # the number ("이상", "이내") is still visible to the normalizer.
    for match in _PERCENT_BUNUI_RE.finditer(text):
        result = normalize_percent(match.group(0) + text[match.end() : match.end() + 6])
        if result["parse_status"] == "success":
            result["context"] = _context(match.start(), match.end(), 10)
            results.append(result)

    for match in _PERCENT_SLASH_RE.finditer(text):
        result = normalize_percent(match.group(0) + text[match.end() : match.end() + 6])
        if result["parse_status"] == "success":
            result["context"] = _context(match.start(), match.end(), 10)
            results.append(result)

    for match in _PERCENT_RE.finditer(text):
        result = normalize_percent(match.group(0) + text[match.end() : match.end() + 6])
        if result["parse_status"] == "success":
            result["context"] = _context(match.start(), match.end(), 10)
            results.append(result)

    # Parenthesised asides are blanked for amount detection only, so that a
    # figure quoted inside brackets is not read as the clause's own amount.
    for match in _AMOUNT_RE.finditer(re.sub(r"\([^)]*\)", " ", text)):
        result = normalize_amount(match.group(0) + text[match.end() : match.end() + 6])
        if result["parse_status"] == "success":
            result["context"] = _context(match.start(), match.end(), 15)
            results.append(result)

    for match in _PERIOD_RE.finditer(text):
        result = normalize_period(match.group(0) + text[match.end() : match.end() + 6])
        if result["parse_status"] == "success":
            result["context"] = _context(match.start(), match.end(), 15)
            results.append(result)

    return results
