"""지역 이름 읽기. 지역은 닫힌 어휘라 사전에 있는 이름만 지역으로 본다(추출·판정 공용).

공고의 지역 요건을 낱말 꼴(…시·…군·…구)로 짐작하면 조사가 붙은 낱말("의북구")이나 지명이 없는 문장
("국내에 본사와 생산공장을 갖추어야", "지역제한", "해당 시·도의 관할구역 안")이 지역 값이 된다. 그런 값은
어떤 회사와도 일치하지 않아 모든 회사를 '미달' 로 만든다(2026-10-06 표본). 그래서

  1. 원문에서 조사를 걷어낸다 — "전남광주통합특별시의 북구" → "전남광주통합특별시 북구".
  2. 시·도 이름과 시·군·구 사전(region_vocab, 기관 주소에서 만든 것)에 있는 이름만 지역으로 읽는다.
  3. 판정도 이름끼리 맞춘다 — 같은 시·군·구인가, 시·도가 같은 곳인가. 행정구역 포함 관계를 낱말로
     짐작하지 않는다.
"""
from __future__ import annotations

import re

from bidengine.normalization.region_vocab import SIGUNGU_PARENTS

# 시·도 이름 -> 정식 이름
SIDO_CANONICAL: dict[str, str] = {
    "서울특별시": "서울특별시", "부산광역시": "부산광역시", "대구광역시": "대구광역시", "인천광역시": "인천광역시",
    "광주광역시": "광주광역시", "대전광역시": "대전광역시", "울산광역시": "울산광역시",
    "세종특별자치시": "세종특별자치시", "세종특별시": "세종특별자치시",
    "경기도": "경기도", "강원특별자치도": "강원특별자치도", "강원도": "강원특별자치도",
    "충청북도": "충청북도", "충청남도": "충청남도",
    "전북특별자치도": "전북특별자치도", "전라북도": "전북특별자치도", "전라남도": "전라남도",
    "경상북도": "경상북도", "경상남도": "경상남도",
    "제주특별자치도": "제주특별자치도", "제주도": "제주특별자치도",
    "전남광주통합특별시": "전남광주통합특별시",
}
# 통합 전 시·도 -> 통합 후. 통합 전 이름으로 등록된 회사는 통합 시·도 안에 있다.
SIDO_MERGED_INTO: dict[str, str] = {"광주광역시": "전남광주통합특별시", "전라남도": "전남광주통합특별시"}

# 지명에 붙는 조사·꾸밈. 이름 앞("의 북구")과 뒤("춘천시에", "공주시 내", "광산구로")에서 걷어낸다.
_TRAILING = ("에서의", "에서", "으로", "에는", "에", "의", "내", "안", "로", "를", "을", "은", "는", "이", "가", "와", "과", "및", "관내", "일원", "소재")
_LEADING = ("의", "및", "또는", "에", "내")
_SPLIT_RE = re.compile(r"[^가-힣]+")


# 조사·이음말만으로 된 낱말. 지역 낱말 목록에서 뺀다("경상남도 에 있고" 의 "에").
_PARTICLE_WORDS = frozenset({"에", "의", "내", "안", "로", "으로", "에서", "및", "또는", "와", "과", "를", "을", "은", "는", "이", "가"})
# 이름 뒤에 붙여 쓴 서술의 첫머리("보령시에둔", "춘천시소재").
_PREDICATE_HEADS = ("에", "의", "내", "안", "로", "으로", "소재", "관내", "일원", "둔", "있", "위치")


def _strip(token: str) -> str:
    """사전에 있는 이름이 나올 때까지 조사를 걷어낸다. 끝내 안 나오면 원래 낱말을 돌려준다."""
    if token in SIDO_CANONICAL or token in SIGUNGU_PARENTS:
        return token
    # 붙여 쓴 꼴: 사전 이름 + 서술("보령시에둔"). 가장 긴 이름부터 본다.
    for length in range(min(len(token) - 1, 8), 1, -1):
        head, rest = token[:length], token[length:]
        if (head in SIGUNGU_PARENTS or head in SIDO_CANONICAL) and rest.startswith(_PREDICATE_HEADS):
            return head
    candidates = [token]
    for lead in _LEADING:
        if token.startswith(lead):
            candidates.append(token[len(lead):])
    for candidate in list(candidates):
        for tail in _TRAILING:
            if candidate.endswith(tail) and len(candidate) > len(tail):
                candidates.append(candidate[: -len(tail)])
    for candidate in candidates:
        if candidate in SIDO_CANONICAL or candidate in SIGUNGU_PARENTS:
            return candidate
    return token


def region_tokens(text: str) -> list[str]:
    """한글 낱말로 자르고 조사를 걷어낸 목록. 붙여 쓴 "충청남도보령시" 는 시·도와 시·군·구로 가른다."""
    tokens: list[str] = []
    for raw in _SPLIT_RE.split(text or ""):
        if not raw:
            continue
        sido = next((name for name in sorted(SIDO_CANONICAL, key=len, reverse=True) if raw.startswith(name)), None)
        if sido and raw != sido:
            tokens.append(sido)
            raw = raw[len(sido):]
        token = _strip(raw)
        if token and token not in _PARTICLE_WORDS:
            tokens.append(token)
    return tokens


def find_regions(text: str) -> tuple[list[str], list[str]]:
    """(시·도 정식 이름들, 시·군·구 이름들). 나온 순서, 중복 없이."""
    sidos: list[str] = []
    sigungus: list[str] = []
    for token in region_tokens(text):
        if token in SIDO_CANONICAL:
            name = SIDO_CANONICAL[token]
            if name not in sidos:
                sidos.append(name)
        elif token in SIGUNGU_PARENTS and token not in sigungus:
            sigungus.append(token)
    return sidos, sigungus


def sigungu_after(text: str, sido: str) -> str | None:
    """원문에서 시·도 이름 바로 다음 낱말이 시·군·구면 그 이름. 모델이 값으로 시·도만 짚었을 때 원문대로 좁힌다."""
    tokens = region_tokens(text)
    for index, token in enumerate(tokens[:-1]):
        if SIDO_CANONICAL.get(token) == sido and tokens[index + 1] in SIGUNGU_PARENTS:
            return tokens[index + 1]
    return None


def same_sido(observed: str, required: str) -> str:
    """'match' | 'contained' (통합 전 이름의 회사, 통합 후 요건) | 'too_coarse' (반대) | 'none'."""
    if observed == required:
        return "match"
    if SIDO_MERGED_INTO.get(observed) == required:
        return "contained"
    if SIDO_MERGED_INTO.get(required) == observed:
        return "too_coarse"
    return "none"


def region_name_relation(observed: str, required: str) -> str | None:
    """이름으로 본 지역 관계. 요건에 아는 지역 이름이 없으면 None (부르는 쪽이 예전 방식으로 판단한다).

    'match' | 'contained' | 'too_coarse' | 'none'
    """
    required_sidos, required_subs = find_regions(required)
    if not required_sidos and not required_subs:
        return None
    observed_sidos, observed_subs = find_regions(observed)
    if not observed_sidos and not observed_subs:
        return None
    if not observed_sidos and observed_subs:
        # 시·군·구만 적힌 프로필 — 그 이름이 쓰이는 시·도가 하나면 그 시·도로 본다.
        parents = {SIDO_CANONICAL[p] for name in observed_subs for p in SIGUNGU_PARENTS[name]}
        observed_sidos = sorted(parents) if len(parents) == 1 else []

    sido_relation = "match"
    if required_sidos and observed_sidos:
        relations = [same_sido(o, r) for o in observed_sidos for r in required_sidos]
        sido_relation = next((rel for rel in ("match", "contained", "too_coarse") if rel in relations), "none")
        if sido_relation == "none":
            return "none"

    if required_subs:
        if not observed_subs:
            return "too_coarse"            # "충청남도" 회사로는 "충청남도 보령시" 안인지 알 수 없다
        if not set(observed_subs) & set(required_subs):
            return "none"
        return "match" if sido_relation in ("match", "contained") else "too_coarse"
    if not required_sidos:
        return None
    if not observed_sidos:
        return "too_coarse"
    return "match" if sido_relation in ("match", "contained") else sido_relation
