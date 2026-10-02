"""Deterministic normalization helpers for AI-extracted source strings."""

# NOTE(LLM/RAG 이식): `extract_values` 를 공개 목록에 추가했습니다.
# 나머지 normalize_* 는 슬롯 하나의 값을 정규화하는 함수라 "이 문자열을 숫자로"가
# 되지만, 조항검토는 반대 방향입니다 — 공고 문장에서 어떤 수치가 몇 개 나오는지
# 모르는 채로 훑어야 합니다. 그래서 문장을 통째로 받아 값을 전부 뽑는 함수가
# 필요했고, 그게 `extract_values` 입니다.
from bidengine.normalization.numbers import (
    COMPARATORS,
    extract_values,
    normalize_amount,
    normalize_count,
    normalize_percent,
    normalize_period,
    normalize_value,
    parse_korean_number,
)

__all__ = [
    "COMPARATORS",
    "extract_values",
    "parse_korean_number",
    "normalize_amount",
    "normalize_period",
    "normalize_percent",
    "normalize_count",
    "normalize_value",
]
