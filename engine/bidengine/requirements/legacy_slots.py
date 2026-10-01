"""Adapter from source-grounded extraction slots to canonical requirements.

The extraction layer keeps human-readable Korean slot types as an internal
interface. Production maps those slots into the closed eight-type canonical
taxonomy. Unsupported or incomplete slots become diagnostics rather than being
forced into a judgment-ready requirement.
"""

from __future__ import annotations

import re
from typing import Any

from bidengine.contracts import QualificationRequirement, RequirementOperator, RequirementType
from bidengine.ports import IndustryNameResolver
from bidengine.judgment.clause_safety import GUARD_ASSESSED, assess_clause, strip_decorations, unsafe_clause_reason
from bidengine.judgment.context_guard import decide as decide_context
from bidengine.judgment.rules import _COMPANY_SIZE_ALIASES
from bidengine.requirements.deduplicate import _INDUSTRY_NAME_VALUE_RE, _REGISTRATION_ACT_VALUE_RE

_MIN_PLAUSIBLE_AMOUNT_KRW = 10_000
_COUNT_RE = re.compile(r"(\d+)\s*(?:건|회)\s*(이상|초과|이하|미만)?")
_INDUSTRY_CODE_RE = re.compile(r"업종\s*코드\s*[:：]?\s*([0-9]{4}(?:\s*[,/·]\s*[0-9]{4})*)(?![0-9])")
# 지역값 뒤에 붙는 서술 꼬리 — "전남광주통합특별시에 소재한 업체" → "전남광주통합특별시".
_REGION_TAIL_RE = re.compile(
    r"(?:에|의|을|를)?\s*(?:소재한?|위치한?|있는|둔|두고\s*있는)\s*(?:업체|자|기업|법인|사업자)?\s*$"
)
_SIZE_EXCLUSION_RE = re.compile(
    r"참여\s*(?:제한|불가|배제|금지)"
    r"|참가\s*(?:제한|불가|배제)"
    r"|참여할\s*수\s*없"
    r"|참여\s*(?:를)?\s*(?:제외|배제)"
    r"|입찰\s*참가\s*자격\s*(?:을)?\s*제한"
)


# 닫힌 식별자 — 사람이 달리 쓸 수 없는 값. 업종코드 4자리, 세부품명번호 10자리.
# 모델이 유형을 뭐라고 붙이든 이 숫자는 원문에 그대로 있다.
_PRODUCT_CODE_RE = re.compile(r"(?<![0-9])([0-9]{10})(?![0-9])")
_REGISTRATION_CONTEXT_RE = re.compile(r"등록|신고|영업|허가|면허")
_PRODUCT_CONTEXT_RE = re.compile(r"직접\s*생산\s*확인|세부\s*품명|품명\s*번호")


def _compact(text: str) -> str:
    """닫힌 식별자를 읽을 때 쓰는 본문 — 공백·줄바꿈을 전부 걷어낸다.

    [재현 2026-09-15, 골든 01688607] PDF 원문이 "[업⏎종코드: 5898]" 처럼 **낱말 안에서** 줄을
    바꾼다. 모델 raw 는 원문 구간으로 스냅되므로 그 줄바꿈이 그대로 들어오고, "업종코드"
    정규식이 못 읽어 코드 5898 대신 이름 값으로 떨어졌다. 숫자는 사람이 달리 못 쓰는 값이라
    공백을 걷어내도 뜻이 안 바뀐다.
    """
    return re.sub(r"\s+", "", text or "")


# PDF 추출은 숫자 사이에 공백을 끼운다("업종코드 : 1 4 6 8"). 숫자 넷 사이에 **공백만** 있고
# 다른 글자가 없으면 같은 코드다. 하이픈·점 같은 글자가 끼거나 숫자가 다섯 이상이면 코드로
# 보지 않는다.
_LABELLED_CODE_RE = re.compile(
    r"업\s*종\s*코\s*드\s*[:：]?\s*(?P<code>[0-9](?:\s*[0-9]){3})(?!\s*[0-9])"
)


# ── 값 정규화 ─────────────────────────────────────────────────────────────────
#
# [실측 2026-10-01] 같은 조항의 값이 실행마다 표기만 달랐다 — "엔지니어링 사업자" ↔
# "엔지니어링사업자", "( 세부품명 : X , Y )" ↔ "(세부품명: X, Y)", "대기업 및 중견기업" ↔
# "대기업 및 중견기업 참여 제한". 판정은 대부분 공백을 무시하지만 차수 비교(decision_payload)는
# 값을 그대로 보므로 표기 차이가 '수정됨' 이 된다. 값은 표기 하나로 맞춘다. 원문은 raw 에 있다.
_SPACE_AROUND_PUNCT_RE = re.compile(r"\s*([(\[{])\s*|\s*([)\]}])|\s+([,，:：])|([,，:：])(?=\S)")
_HANGUL_GAP_RE = re.compile(r"(?<=[가-힣])\s+(?=[가-힣])")
# 등록·면허 이름으로 쓸 수 없는 낱말. 모델이 "신고 및 실적이 등록" 을 쪼개 "실적" 만 값으로
# 낼 때가 있다(gpt-6-luna 2/3). 이것은 요건이 아니라 쪼개다 남은 조각이다.
_GENERIC_REGISTRATION_WORDS = {
    "실적", "등록", "신고", "자격", "인증", "면허", "허가", "업체", "사업자", "증명서", "확인서", "등록증",
}


def _tidy_punctuation(match: re.Match[str]) -> str:
    opening, closing, before, after = match.groups()
    if opening:
        return opening
    if closing:
        return closing
    if before:
        return before
    return after + " "


# 이름·역할 값 앞의 법령 인용("건설기술진흥법에 의한 …")과 등록 이름 뒤의 서술부("…로 신고 및
# 실적이 등록되어 있는 자")는 이름이 아니다. 조항 단위 추출에서 남은 흔들림이 거의 이것이었다 —
# 같은 조항에서 모델이 값을 어디까지 잘라 오느냐(2026-10-01 실측).
_LEADING_STATUTE_RE = re.compile(r"^[^,，]*?(?:법|법령|법률|시행령|규정|고시)\s*에\s*(?:의한|따른|따라|의거한?)\s+")
_REGISTRATION_PREDICATE_TAIL_RE = re.compile(r"(?<=[가-힣)])\s*(?:으로|로)\s*(?:신고|등록)\S*(?:\s.*)?$")


def normalize_value_text(value: str, *, req_type: str) -> str:
    """값의 표기를 하나로 맞춘다. 공백, 이름 앞 법령 인용, 등록 이름 뒤 서술부만 다룬다."""
    text = " ".join(str(value).split())
    if req_type in {"REGISTRATION_CERTIFICATION", "STAFF"}:
        text = _LEADING_STATUTE_RE.sub("", text)
    if req_type == "REGISTRATION_CERTIFICATION":
        text = _REGISTRATION_PREDICATE_TAIL_RE.sub("", text)
    text = _SPACE_AROUND_PUNCT_RE.sub(_tidy_punctuation, text)
    text = " ".join(text.split())
    if req_type == "REGISTRATION_CERTIFICATION":
        # 등록·면허 이름은 띄어쓰기가 표기마다 다르다("엔지니어링 사업자"). 한글 사이 공백을 없앤다.
        text = _HANGUL_GAP_RE.sub("", text)
    return text


def is_generic_registration_name(value: str) -> bool:
    return re.sub(r"[\s()·ㆍ,]", "", value or "") in _GENERIC_REGISTRATION_WORDS


def strip_size_restriction(value: str) -> str:
    """"대기업 및 중견기업 참여 제한" → "대기업 및 중견기업". 배제 뜻은 scope.restriction 이 든다."""
    return " ".join(_SIZE_EXCLUSION_RE.sub(" ", value or "").split())


def labelled_industry_codes(text: str) -> set[str]:
    """'업종코드' 라벨 바로 뒤의 네 자리 코드. 숫자 사이 공백은 무시하고 다른 글자는 허용하지 않는다."""
    return {re.sub(r"\s+", "", m.group("code")) for m in _LABELLED_CODE_RE.finditer(text or "")}


# 회사 규모 낱말도 닫힌 어휘다 — 소상공인·소기업·중소기업·중견기업·대기업 다섯 개뿐이고,
# 판정기는 이 다섯 낱말을 열쇠로 허용 규모 집합을 찾는다(`_COMPANY_SIZE_ALIASES`).
#
# [재현 2026-09-15, 골든 17개 실측] 그런데 모델은 "중·소기업·소상공인", "중소기업자 및
# 소상공인" 처럼 낱말을 이어 붙여 낸다. 그 값은 alias 표에 없어서 판정기가 문자열 비교로
# 떨어지고, SMALL 회사가 **UNSATISFIED** 를 받았다(실제 실행으로 확인). 같은 사실이
# 실행마다 COMPANY_SIZE / "…확인서" REGISTRATION_CERTIFICATION / 검증 탈락 세 모양으로 갈려
# 7개 공고가 흔들렸다. 골든셋은 전부 COMPANY_SIZE(allowed 집합)로 본다.
#
# 이어 붙인 값은 각 낱말의 허용 집합의 합집합이다 — "소기업·소상공인" = 소기업(MICRO,SMALL)
# ∪ 소상공인(MICRO) = 소기업. 합집합이 정확히 어느 한 낱말의 집합과 같을 때만 그 낱말로
# 정규화한다. "대기업 및 중견기업" 처럼 어느 낱말과도 안 맞으면 손대지 않는다(그건 참여
# 제한 조항이고 기존 EXCLUDE 경로가 맞게 처리한다). 법령명 안의 낱말("「중소기업기본법」에
# 따른 소상공인")이 섞이지 않게 먼저 인용을 벗긴다.
_SIZE_WORD_RE = re.compile(r"중견기업|대기업|중소기업|소기업|소상공인")
# "중·소기업" 은 중기업·소기업을 가운뎃점으로 이어 쓴 것이다 — 점을 걷어내면 "중소기업" 이다.
_SIZE_JOINERS_RE = re.compile(r"[·ㆍ.\s]")
# 규모 확인서 이름 — 낱말·'자'·및/와/과·확인서/증명서 접미만으로 이루어진 값(점·공백은 미리
# 걷어낸다). "ISO 9001" 처럼 고유명사가 섞이면 진짜 인증이므로 여기 안 걸린다.
_SIZE_CERT_NAME_RE = re.compile(
    r"^(?:(?:중견기업|대기업|중소기업|소기업|소상공인)자?[,및와과]*)+(?:확인서|증명서|확인증)?$"
)


def _size_text(text: str) -> str:
    return _SIZE_JOINERS_RE.sub("", strip_decorations(text or ""))


def company_size_alias(text: str) -> str | None:
    """규모 낱말들의 허용 집합 합집합이 정확히 한 낱말의 집합이면 그 낱말. 아니면 None."""
    allowed: set[str] = set()
    for word in _SIZE_WORD_RE.findall(_size_text(text)):
        allowed |= _COMPANY_SIZE_ALIASES[word]
    if not allowed:
        return None
    return next((key for key, sizes in _COMPANY_SIZE_ALIASES.items() if sizes == allowed), None)


def is_company_size_certificate_name(name: str) -> bool:
    return bool(_SIZE_CERT_NAME_RE.fullmatch(_size_text(name)))


# "A(1257) 또는 B(6770) 또는 C(6786) 등록업체" — 안전 가드는 이것을 막는다. 하나로
# 줄일 수 없는 조건을 충족/미충족으로 단정하면 안 되기 때문이다. 옳은 판단이지만,
# **ANY_OF 가 바로 그 '또는' 의 안전한 표현**이다. 줄이지 않고 관계를 그대로 담을 수
# 있으면 막을 이유가 없다. 그래서 이 모양 하나만 좁게 연다.
#
# 조건을 좁게 두는 이유는 '또는' 이 늘 대등한 선택지는 아니기 때문이다 — "A 또는
# B 기준을 충족한 업체" 처럼 뒤쪽이 예외·완화 조항이면 ANY_OF 가 아니다. 그래서
# 갈라진 조각이 **전부 업종명(업종코드) 하나씩** 일 때만 인정한다.
_ALTERNATION_SPLIT_RE = re.compile(r"\s*또는\s*")
_EXCEPTION_WORDS_RE = re.compile(
    r"다만|단서|예외|제외|불구하고|각\s*호|아니(?:어야|하여야|한)|해당되지|경우에\s*한"
)
# "기타자유업(행사대행업)(9901)" 처럼 업종명 뒤에 설명 괄호가 하나 더 끼기도 한다(01684825, J20).
_NAMED_INDUSTRY_CODE_RE = re.compile(r"[가-힣A-Za-z·ㆍ\s]{2,}?업\s*\)?\s*\(\s*([0-9]{4})\s*\)")
# [재현 2026-09-15, 검수] "가공업(1257)을 등록하고 ISO 9001을 보유한 업체 또는 운반업(1227)을
# 등록한 업체" 를 실제로 돌리면 ["1257","1227"] 를 돌려줬다. 조각마다 코드가 "하나 있는지"만
# 보고 "그것 말고 다른 게 있는지"는 안 봤다 — "AND ISO 9001" 이 조용히 사라진 채
# (1257 AND ISO 9001) OR 1227 이 1257 OR 1227 로 줄었다. 코드 문구를 걷어낸 나머지에 이런
# 낱말이 남으면 코드 하나로 안 줄어드는 추가 조건이 있다는 뜻이라 ANY_OF 를 접지 않는다.
_EXTRA_CONDITION_RE = re.compile(
    r"보유|겸비|겸한|충족|이상|미만|이내|해당|자격증|인증서?|증명서|면허증"
    r"|ISO\s*[0-9]|KS\s*[A-Za-z0-9]|동시에|함께|모두|각각"
)


def industry_code_alternation(raw: str) -> list[str] | None:
    """'또는' 으로 갈린 조각이 전부 업종명(코드) 하나씩이면 그 코드 목록. 아니면 None."""
    if _EXCEPTION_WORDS_RE.search(raw):
        return None
    parts = _ALTERNATION_SPLIT_RE.split(raw)
    if len(parts) < 2:
        return None
    codes: list[str] = []
    for part in parts:
        found = _NAMED_INDUSTRY_CODE_RE.findall(_compact(part))
        if len(found) != 1:
            return None
        # 코드 문구를 뺀 나머지에 "보유·충족·ISO…" 같은 낱말이 남으면, 이 조각은 코드
        # 하나로 안 줄어드는 다른 조건과 AND 로 묶여 있다는 뜻이다. 그 조건은 우리가 못
        # 줄이므로 전체를 ANY_OF 로 열지 않는다 — 위 가드가 UNMAPPED 로 안전하게 받는다.
        remainder = _NAMED_INDUSTRY_CODE_RE.sub("", part, count=1)
        if _EXTRA_CONDITION_RE.search(remainder):
            return None
        codes.append(found[0])
    if len(set(codes)) != len(codes):
        return None
    return codes


# ── 등록·면허 이름의 대안 ("A 또는 B 로 등록한 자") ─────────────────────────────
#
# [실측 2026-09-30] 실공고 4건 중 2건에서 핵심 등록 요건이 '또는' 때문에 통째로 빠졌다
# (docs/experiments/2026-09-30). 업종코드끼리의 '또는' 은 위에서 이미 ANY_OF 로 담는다.
# 여기서는 **이름**끼리의 '또는' 을 담는다. 두 모양이 있다.
#
#   괄호형  "건축(또는 토목건축)공사업", "의료기기(또는 의료용기기, 의료용기구및기기)"
#   나열형  "건설엔지니어링업(종합) 또는 건설엔지니어링업(설계․사업관리-일반) … 로 등록한 자"
#
# '또는' 이 전부 대안은 아니다. 배제 조건("부정당업자 제재 중 … 또는 파산 중인 자")을
# 대안으로 읽으면 뜻이 뒤집히고, 절차("현금 또는 보증보험으로 납부")는 자격이 아니다.
# 그래서 여는 조건을 좁게 둔다 — 문장이 등록·신고를 **요구하는 서술로 끝나고**, 배제·예외
# 낱말이 없고, 이름 말고 다른 조건(지역·인원·금액·보유)이 섞이지 않을 때만.
_REGISTRATION_TAIL_RE = re.compile(
    r"(?:으로|로|을|를)?\s*(?:등록|신고)(?:을|를)?\s*(?:필한|마친|한|된|하여야\s*하는)?\s*"
    r"(?:자|업체|사업자|업자)(?:이어야\s*(?:합니다|한다))?\s*[.。]?\s*$"
    r"|등록\s*업체\s*[.。]?\s*$"
)
_EXCLUSION_RE = re.compile(
    r"제재|파산|부도|정지|부정당|무효|참가할\s*수\s*없|참여할\s*수\s*없|중인\s*자|중에\s*있는|취소"
)
_NON_NAME_CONDITION_RE = re.compile(
    r"소재|영업소|본점|지역|이상|이하|미만|초과|이내|보유|인\s*이상|명|억|만원|실적|기술자|감리원|확인을\s*받"
)
_PAREN_ALTERNATION_RE = re.compile(
    r"(?P<head>[가-힣A-Za-z0-9·ㆍ․]+)\(\s*또는\s*(?P<alts>[^()]+?)\s*\)(?P<tail>[가-힣A-Za-z0-9·ㆍ․]*)"
)
_NAME_LEAD_RE = re.compile(
    r"^.*?(?:에\s*(?:의한|따른|따라|의거한?|근거한?))\s*"
)
_NAME_PREDICATE_RE = re.compile(
    r"(?:(?:으로|로|을|를)?\s*(?:등록|신고)(?:을|를)?\s*(?:필한|마친|한|된)?\s*(?:자|업체|사업자)?(?:이어야\s*(?:합니다|한다))?"
    r"|등록\s*업체)\s*[.。]?\s*$"
)
_OTHER_ALTERNATION_RE = re.compile(r"다만|각\s*호|중\s*하나|어느\s*하나|이거나|이며|및")


def _clean_name(part: str) -> str:
    text = strip_decorations(part)
    text = _NAME_LEAD_RE.sub("", text)
    text = _NAME_PREDICATE_RE.sub("", text)
    text = re.sub(r"^(?:[0-9]+\)|[가-힣]\.|[-ㅇ○□■·])\s*", "", text.strip())
    return text.strip(" ,")


# 대안 등록 요건 뒤에 붙은 지역 조건 — "…공사업 등록업체로서 입찰공고일 전일부터 계약체결일까지
# 주된 영업소의 소재지를 경상남도에 둔 업체"(C03 실측). 이 꼬리 하나만 떼어 지역 요건으로 담고,
# 앞부분은 대안 묶음으로 연다. 둘은 AND 다. 꼬리 모양이 이것과 정확히 맞을 때만 뗀다.
# 행정구역(시·도) 이름. 지역은 닫힌 어휘라 '또는' 으로 나열돼도 각 이름을 그대로 비교할 수 있다.
_REGION_NAME = r"[가-힣]{2,}?(?:특별자치시|특별자치도|특별시|광역시|도)"
_REGION_LIST = rf"(?P<regions>{_REGION_NAME}(?:\s*(?:또는|,|，|·|ㆍ)\s*{_REGION_NAME})*)"
_REGION_PREDICATE = (
    r"\s*(?:내|안|지역)?\s*에?\s*(?:둔|두고\s*있는|있는|소재한|소재하는|위치한)\s*(?:업체|자|사업자)\s*[.。]?\s*$"
)
_REGION_CONDITION_RE = re.compile(
    r"\s*(?:으로서|로서|이며|이고|이면서)\s*"
    r"(?:[^.。]*?까지\s*)?"  # 기간 단서("입찰공고일 전일부터 계약체결일까지")
    r"(?:주된\s*영업소|본점|본사|주\s*사무소)(?:의)?\s*소재지(?:를|가|는)?\s*"
    + _REGION_LIST + _REGION_PREDICATE
)
# 지역 요건만으로 된 문장 — "본점 소재지가 서울특별시 또는 경기도에 있는 업체".
_REGION_ONLY_RE = re.compile(
    r"^(?:[0-9]+\)|[가-힣]\.|[-ㅇ○□■·])?\s*"
    r"(?:[^.。]*?까지\s*)?"
    r"(?:(?:주된\s*영업소|본점|본사|주\s*사무소)(?:의)?\s*)?(?:소재지|주소지)?(?:를|가|는|이)?\s*"
    + _REGION_LIST + _REGION_PREDICATE
)


# 시·도는 닫힌 어휘다. 조항에서 이름을 세면 '또는' 이 지역끼리의 대안인지(이름이 둘 이상) 주소 서류에 대한
# 부연인지(이름이 하나) 코드가 가를 수 있다. "…도" 로 끝나는 낱말(연도·제도·정도)을 지역으로 읽지 않도록
# 이름을 직접 적는다.
_SIDO_RE = re.compile(
    r"(?:서울|전남광주통합)특별시|(?:부산|대구|인천|광주|대전|울산)광역시|세종특별(?:자치)?시"
    r"|(?:강원|전북|제주)특별자치도|경기도|강원도|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|제주도"
)
_SIDO_ALIASES = {
    "강원도": "강원특별자치도", "전라북도": "전북특별자치도", "제주도": "제주특별자치도", "세종특별시": "세종특별자치시",
}
# 목록에 없는 시·도 이름이 남아 있는지 본다. 이 접미사는 지역 이름에만 쓰인다.
_UNKNOWN_SIDO_RE = re.compile(r"특별자치시|특별자치도|특별시|광역시")


def sido_names(text: str) -> list[str]:
    """글에 나오는 시·도 이름(나온 순서, 중복 없이). PDF 가 낱말 안에서 줄을 바꾸므로 공백을 걷고 읽는다."""
    compact = _compact(text or "")
    names = list(dict.fromkeys(_SIDO_ALIASES.get(name, name) for name in _SIDO_RE.findall(compact)))
    if _UNKNOWN_SIDO_RE.search(_SIDO_RE.sub(" ", compact)):
        # 아는 이름을 걷어내고도 시·도 접미사가 남았다. 모르는 지역을 하나로 세어, 관계를 모르는 채로
        # 한 지역만 확정하는 일을 막는다.
        names.append("미상 시·도")
    return names


def value_name_alternatives(value: str) -> list[str] | None:
    """값 구간 안에서 '또는' 으로 나열된 이름들. "건축공사업(또는 토목건축공사업)" → 두 이름. 아니면 None.

    조항 전체가 아니라 모델이 값으로 짚은 구간만 본다 — 구간 밖의 '또는' 은 이 값의 대안이 아니다.
    """
    text = " ".join((value or "").split())
    text = re.sub(r"\s*([()（）,，])\s*", r"\1", text)
    # '또는' 이 낱말로 서 있을 때만 대안이다. "진공또는원심농축기" 는 품명 하나다. 숫자가 든 값(업종코드·
    # 세부품명번호)은 코드 경로의 몫이라 여기서 이름으로 쪼개지 않는다.
    if not re.search(r"(?:\s|\()또는\s", text) or re.search(r"[0-9]{4}", text):
        return None
    paren = list(_PAREN_ALTERNATION_RE.finditer(text))
    if len(paren) == 1 and "또는" not in _PAREN_ALTERNATION_RE.sub(" ", text):
        match = paren[0]
        tail = re.sub(r"^(?:으로|로|을|를|에|의|이|가)$", "", match.group("tail"))
        alternatives = [a.strip() for a in re.split(r"\s*[,，]\s*|\s*또는\s*", match.group("alts")) if a.strip()]
        names = [match.group("head") + tail] + [alt + tail for alt in alternatives]
    elif not paren:
        names = [_clean_name(part) for part in _ALTERNATION_SPLIT_RE.split(text)]
    else:
        return None
    if len(names) < 2 or any(not name or len(name) > 40 for name in names):
        return None
    if len({_compact(name) for name in names}) != len(names):
        return None
    return names


def _region_names(match: re.Match[str]) -> list[str]:
    names = re.findall(_REGION_NAME, match.group("regions"))
    return list(dict.fromkeys(names))


def region_alternation(raw: str) -> list[str] | None:
    """지역 요건만으로 된 문장의 지역 이름들. 둘 이상이면 대안(OR)이다. 아니면 None."""
    collapsed = " ".join((raw or "").split())
    if _EXCEPTION_WORDS_RE.search(collapsed) or _EXCLUSION_RE.search(collapsed):
        return None
    match = _REGION_ONLY_RE.search(collapsed)
    if match is None:
        return None
    names = _region_names(match)
    return names if len(names) >= 2 else None


def registration_alternation_with_region(raw: str) -> tuple[list[str], list[str]] | None:
    """대안 이름 목록과, 문장 끝에 붙은 지역 조건의 지역 이름들(없으면 빈 목록)."""
    collapsed = " ".join((raw or "").split())
    match = _REGION_CONDITION_RE.search(collapsed)
    if match is None:
        names = registration_alternation(raw)
        return (names, []) if names else None
    names = registration_alternation(collapsed[: match.start()])
    return (names, _region_names(match)) if names else None


def registration_alternation(raw: str) -> list[str] | None:
    """'또는' 으로 갈린 등록·면허 **이름** 목록. 안전하게 대안으로 읽을 수 없으면 None."""
    collapsed = " ".join((raw or "").split())
    # PDF 추출은 괄호·쉼표 앞뒤에 공백을 끼운다("의료기기 ( 또는 의료용기기 , …").
    collapsed = re.sub(r"\s*([()（）,，])\s*", r"\1", collapsed)
    collapsed = re.sub(r"([,，])", r"\1 ", collapsed)
    if "또는" not in collapsed:
        return None
    if _EXCEPTION_WORDS_RE.search(collapsed) or _EXCLUSION_RE.search(collapsed):
        return None
    # 업종코드가 박힌 조항은 코드 경로(industry_code_alternation)의 몫이다. 거기서 일부러
    # 열지 않는 모양("업종코드: 1468 또는 업종코드: 0036")을 이름 경로가 대신 열면 안 된다.
    if re.search(r"[0-9]{4}", collapsed):
        return None
    if not _REGISTRATION_TAIL_RE.search(collapsed):
        return None
    body = strip_decorations(collapsed)

    paren = list(_PAREN_ALTERNATION_RE.finditer(body))
    if paren:
        # 괄호 밖에도 '또는' 이 있으면 두 층의 대안이라 여기서 풀지 않는다.
        if len(paren) != 1 or "또는" in _PAREN_ALTERNATION_RE.sub(" ", body):
            return None
        match = paren[0]
        rest = _NAME_PREDICATE_RE.sub("", (body[: match.start()] + " " + body[match.end():]))
        if _NON_NAME_CONDITION_RE.search(rest) or _OTHER_ALTERNATION_RE.search(rest):
            return None
        head = match.group("head")
        # 괄호 바로 뒤가 조사뿐이면("…)로 등록된") 이름의 일부가 아니다.
        tail = re.sub(r"^(?:으로|로|을|를|에|의|이|가)$", "", match.group("tail"))
        alternatives = [a.strip() for a in re.split(r"\s*[,，]\s*|\s*또는\s*", match.group("alts")) if a.strip()]
        names = [head + tail] + [alt + tail for alt in alternatives]
    else:
        parts = _ALTERNATION_SPLIT_RE.split(body)
        names = [_clean_name(part) for part in parts]
        for part, name in zip(parts, names):
            if _NON_NAME_CONDITION_RE.search(_NAME_PREDICATE_RE.sub("", part)) or _OTHER_ALTERNATION_RE.search(name):
                return None
    if len(names) < 2 or any(not name or len(name) > 40 for name in names):
        return None
    if len({_compact(name) for name in names}) != len(names):
        return None
    return names


def salvage_closed_identifier(raw: str) -> tuple[RequirementType, str] | None:
    """분류가 '기타요건' 으로 와도 원문의 닫힌 식별자로 유형을 되살린다.

    되살리는 기준을 좁게 둔다 — 식별자가 **정확히 하나**이고, 그것이 등록·신고 맥락에
    쓰였을 때만. 여러 개면 AND/OR 관계를 모르므로 살리지 않는다(이미 업종요건 경로가
    같은 이유로 멈춘다). 숫자가 아닌 표현은 건드리지 않는다 — 지역명·인증명처럼 사람이
    달리 쓸 수 있는 값을 여기서 추측하기 시작하면 틀린 확정으로 간다.
    """
    industry_codes = {
        code
        for group in _INDUSTRY_CODE_RE.findall(_compact(raw))
        for code in re.findall(r"[0-9]{4}", group)
    }
    if len(industry_codes) == 1 and _REGISTRATION_CONTEXT_RE.search(raw):
        return "INDUSTRY", next(iter(industry_codes))

    product_codes = set(_PRODUCT_CODE_RE.findall(_compact(raw)))
    if len(product_codes) == 1 and _PRODUCT_CONTEXT_RE.search(raw):
        return "REGISTRATION_CERTIFICATION", next(iter(product_codes))

    return None


def _squash_name(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _op(word: str | None) -> RequirementOperator | None:
    return {"이상": ">=", "초과": ">", "이하": "<=", "미만": "<"}.get(word)  # type: ignore[return-value]


def _performance_scope(slot: dict[str, Any], *, aggregation: str | None = None) -> dict[str, Any]:
    scope: dict[str, Any] = {}
    if aggregation is not None:
        scope["aggregation"] = aggregation
    client_requirement = (slot.get("실적기관_raw") or "").strip()
    if client_requirement:
        scope["client_requirement"] = client_requirement
    experience_field = (slot.get("경험분야_raw") or "").strip()
    if experience_field:
        scope["experience_field"] = experience_field
    return scope


def adapt_legacy_slot(
    slot: dict[str, Any],
    *,
    notice_version_id: str,
    key_prefix: str,
    industry_resolver: IndustryNameResolver | None = None,
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """Map one validated extraction slot into zero or more canonical requirements."""
    slot_type = slot.get("유형")
    raw = (slot.get("raw") or "").strip()
    # [재현 2026-09-15, 검수 2차] 나라장터 절차 가드가 raw 만 보면 놓치는 경우가 있었다 —
    # 01634263-003 를 5회 중 1회는 모델이 "「국가종합전자조달시스템 입찰참가자격등록규정」"
    # 을 raw 가 아니라 등록인증_raw 에 담고, raw 에는 "입찰참가등록 마감일시까지 …" 꼬리만
    # 남겼다. 어느 필드에 담겼는지는 모델 마음이라 가드는 둘을 합쳐서 본다. 요건에 실제로
    # 저장되는 raw 는 그대로(raw=raw) — 가드 판단에만 쓴다.
    registration_name = (slot.get("등록인증_raw") or "").strip()
    guard_text = f"{raw} {registration_name}" if registration_name else raw
    unsafe_reason = unsafe_clause_reason(guard_text)
    # 조항의 극성이 붙어 있으면(clause_polarity) 낱말 가드를 맥락으로 다시 판단한다. 붙어 있지 않으면
    # 아래는 전부 예전 그대로다.
    context = decide_context(
        guard_text,
        slot.get("_clause_polarity"),
        exclusion_representable=slot_type == "기업규모요건" and bool(_SIZE_EXCLUSION_RE.search(raw)),
    )
    if context.action == "ABSTAIN":
        return [], [{"code": "UNMAPPED_REQUIREMENT", "raw": raw, "reason": context.reason}]
    guard_lifted = context.action == "KEEP"
    alternation = (
        industry_code_alternation(raw)
        if unsafe_reason == "ALTERNATIVE_OR_EXCEPTION_RULE"
        else None
    )
    alternatives = (
        registration_alternation_with_region(raw)
        if unsafe_reason == "ALTERNATIVE_OR_EXCEPTION_RULE" and alternation is None
        else None
    )
    names, attached_regions = alternatives if alternatives else (None, [])
    regions_only = (
        region_alternation(raw)
        if unsafe_reason == "ALTERNATIVE_OR_EXCEPTION_RULE" and alternation is None and names is None
        else None
    )
    if regions_only is not None:
        return _region_requirements(
            raw, regions_only, notice_version_id=notice_version_id, key_prefix=key_prefix
        ), [{"code": "REGION_ALTERNATION", "raw": raw, "regions": list(regions_only)}]
    if unsafe_reason and alternation is None and names is None and not guard_lifted:
        return [], [{"code": "UNMAPPED_REQUIREMENT", "raw": raw, "reason": unsafe_reason}]
    diagnostics: list[dict[str, Any]] = []
    requirements: list[QualificationRequirement] = []
    group_key = f"{key_prefix}-GROUP"

    # Only a single explicit code can replace an industry/registration name.
    # Multiple codes need their AND/OR relationship resolved before mapping.
    industry_codes = {
        code for group in _INDUSTRY_CODE_RE.findall(_compact(raw))
        for code in re.findall(r"[0-9]{4}", group)
    }
    if not industry_codes and registration_name:
        # 모델이 코드를 raw 가 아니라 등록 이름 필드에 담을 때가 있다 — "소프트웨어사업(컴퓨터
        # 관련서비스사업, 업종코드: 1468)"(C01 실측, HWPX·PDF 양쪽). raw 만 읽으면 같은 조항이
        # 실행에 따라 업종코드(닫힌 비교)와 등록 이름(확인 필요)을 오간다.
        industry_codes = labelled_industry_codes(registration_name)
    if not industry_codes:
        # "업종코드 : 1450" 뿐 아니라 "폐기물수집·운반업(1227)" 처럼 업종명 뒤 괄호에
        # 바로 적는 공고가 많다. 업종명이 앞에 붙어 있을 때만 읽는다 — 그냥 네 자리
        # 숫자를 코드로 보면 연도·금액을 업종으로 만든다.
        named = set(_NAMED_INDUSTRY_CODE_RE.findall(_compact(raw)))
        if len(named) == 1:
            industry_codes = named
    if names is not None:
        return _registration_alternation_requirements(
            raw, names, notice_version_id=notice_version_id, key_prefix=key_prefix,
            industry_resolver=industry_resolver, regions=attached_regions,
        )
    if slot_type in {"업종요건", "등록요건"} and len(industry_codes) > 1 and alternation is None:
        return [], [{"code": "UNMAPPED_INDUSTRY", "raw": raw, "reason": "복수 업종코드의 관계를 확인해야 합니다."}]

    def add(
        suffix: str,
        req_type: RequirementType,
        *,
        operator: RequirementOperator | None = None,
        value: int | float | str | None = None,
        unit: str | None = None,
        period_months: float | None = None,
        scope: dict[str, Any] | None = None,
        group_operator: RequirementOperator | str = "ALL_OF",
    ) -> None:
        # 가드 평가를 구조에 새긴다. 판정기·askability 는 이 표시가 있는 요건의 raw 를 다시
        # 읽지 않는다 — ANY_OF 로 담은 '또는' 을 판정기가 또 막던 문제(J14)가 여기서 끝난다.
        assessment = assess_clause(raw, group_operator=str(group_operator))
        complexity = assessment.complexity
        if guard_lifted:
            # 극성으로 가드를 푼 요건이다. 판정기는 raw 를 다시 읽지 않는다(scope.guard). 무엇으로 정했는지 남긴다.
            complexity = "simple"
            scope = {**(scope or {}), "guard_basis": context.basis}
        if isinstance(value, str):
            value = normalize_value_text(value, req_type=req_type)
        if req_type == "STAFF" and scope and isinstance(scope.get("role"), str):
            scope = {**scope, "role": normalize_value_text(scope["role"], req_type="STAFF")}
        if req_type == "REGISTRATION_CERTIFICATION" and isinstance(value, str) and is_generic_registration_name(value):
            diagnostics.append({
                "code": "UNMAPPED_REGISTRATION_CERTIFICATION",
                "raw": raw,
                "reason": f"'{value}' 는 등록·면허 이름으로 쓸 수 없는 낱말입니다.",
            })
            return
        requirements.append(
            QualificationRequirement(
                requirement_key=f"{key_prefix}-{suffix}",
                requirement_group_key=group_key,
                group_operator=group_operator,
                notice_version_id=notice_version_id,
                type=req_type,
                operator=operator,
                value=value,
                unit=unit,
                period_months=period_months,
                scope={**(scope or {}), "guard": GUARD_ASSESSED},
                condition_complexity=complexity,
                raw=raw,
            )
        )

    def lifted_name_alternatives(value: str) -> list[QualificationRequirement] | None:
        """가드를 푼 조항에서 값 구간이 이름의 대안("A(또는 B)")이면 ANY_OF 묶음으로 담는다."""
        alternatives = value_name_alternatives(value) if guard_lifted else None
        if alternatives is None:
            return None
        built, extra = _registration_alternation_requirements(
            raw, alternatives, notice_version_id=notice_version_id, key_prefix=key_prefix,
            industry_resolver=industry_resolver,
        )
        diagnostics.extend(extra)
        return [
            item.model_copy(update={"scope": {**item.scope, "guard_basis": context.basis}}) for item in built
        ]

    if alternation is not None:
        # 관계를 줄이지 않고 그대로 담는다 — 코드 하나가 요건 하나, 묶음은 ANY_OF.
        # 판정기는 이 묶음을 "하나라도 충족하면 충족" 으로 읽는다. 안전 가드가 막던
        # 이유(하나로 줄일 수 없다)가 사라지므로 막을 이유도 사라진다.
        for index, code in enumerate(alternation, start=1):
            add(f"INDUSTRY-{index}", "INDUSTRY", operator="MATCH", value=code,
                group_operator="ANY_OF")
        diagnostics.append({
            "code": "INDUSTRY_ALTERNATION",
            "raw": raw,
            "codes": list(alternation),
        })
        return requirements, diagnostics

    if slot_type == "실적요건":
        amount = slot.get("금액_norm") or {}
        period = slot.get("기간_norm") or {}
        period_months = period.get("value") if period.get("parse_status") == "success" else None
        if slot.get("기간_raw") and period_months is None:
            return [], [{"code": "UNMAPPED_PERFORMANCE", "raw": raw, "reason": "기간을 안전하게 정규화하지 못했습니다."}]
        aggregation = "SUM" if re.search(r"합계|합산|누적|총액", raw) else "UNSPECIFIED"

        # [재현 2026-09-15] 급식 실적 조항("1일 평균 800식 이상")에서 정규화기가 0.0333원을
        # 금액으로 만들어 냈다. "실적 금액 >= 0.03원" 은 실적이 하나라도 있으면 무조건
        # 충족이라 틀린 확정 방향이다. 공고의 실적 금액이 만 원 아래일 리 없다 — 그 아래면
        # 금액이 아니라 다른 숫자(식수·인원·비율)를 잘못 읽은 것이므로 판정에 넣지 않는다.
        parsed_amount = amount.get("value") if amount.get("parse_status") == "success" else None
        if parsed_amount is not None and parsed_amount < _MIN_PLAUSIBLE_AMOUNT_KRW:
            diagnostics.append({
                "code": "UNMAPPED_PERFORMANCE",
                "raw": raw,
                "reason": f"금액 {parsed_amount} 은 실적 금액으로 보기 어렵습니다(하한 {_MIN_PLAUSIBLE_AMOUNT_KRW}원).",
            })
            amount = {}
        if amount.get("parse_status") == "success":
            if amount.get("value") is not None:
                add(
                    "AMOUNT",
                    "PERFORMANCE_AMOUNT",
                    operator=amount.get("op"),
                    value=amount.get("value"),
                    unit=amount.get("unit") or "KRW",
                    period_months=period_months,
                    scope=_performance_scope(slot, aggregation=aggregation),
                )
            elif amount.get("range"):
                amount_range = dict(amount["range"])
                add(
                    "AMOUNT",
                    "PERFORMANCE_AMOUNT",
                    operator="RANGE",
                    unit=amount.get("unit") or "KRW",
                    period_months=period_months,
                    scope={
                        **_performance_scope(slot, aggregation=aggregation),
                        "min": amount_range.get("min"),
                        "min_operator": amount_range.get("min_op"),
                        "max": amount_range.get("max"),
                        "max_operator": amount_range.get("max_op"),
                    },
                )

        count_source = (slot.get("건수_raw") or raw).strip()
        count_match = _COUNT_RE.search(count_source)
        if count_match:
            add(
                "COUNT",
                "PERFORMANCE_COUNT",
                operator=_op(count_match.group(2)) or ">=",
                value=int(count_match.group(1)),
                unit="COUNT",
                period_months=period_months,
                scope=_performance_scope(slot),
            )

        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add(
                "EXPERIENCE",
                "EXPERIENCE_FIELD",
                operator="MATCH",
                value=experience_field,
                period_months=period_months,
                scope={"source": "PERFORMANCE", **_performance_scope(slot)},
            )

        if not requirements:
            diagnostics.append({"code": "UNMAPPED_PERFORMANCE", "raw": raw})

    elif slot_type == "경험분야요건":
        experience_field = (slot.get("경험분야_raw") or "").strip()
        if experience_field:
            add("EXPERIENCE", "EXPERIENCE_FIELD", operator="MATCH", value=experience_field)
        else:
            diagnostics.append({"code": "UNMAPPED_EXPERIENCE_FIELD", "raw": raw})

    elif slot_type == "업종요건":
        industry = (slot.get("업종_raw") or "").strip()
        alternatives_built = lifted_name_alternatives(industry) if not industry_codes else None
        if alternatives_built is not None:
            requirements.extend(alternatives_built)
        elif industry_codes:
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)), scope={"industry_name": industry} if industry else {})
        elif industry:
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=industry)
        else:
            diagnostics.append({"code": "UNMAPPED_INDUSTRY", "raw": raw})

    elif slot_type == "지역요건":
        # [재현 2026-09-15, 우치공원 1/5] 모델이 지역값에 "…에 소재한 업체" 꼬리를 붙여 낼 때가
        # 있다. 판정은 포함 비교라 통과하지만 값이 달라져 실행마다 요건 지문이 갈렸다. 지역명은
        # 행정구역 이름이지 문장이 아니다 — 꼬리를 뗀다.
        region = _REGION_TAIL_RE.sub("", (slot.get("지역_raw") or "").strip()).strip()
        span_regions = sido_names(region) if guard_lifted else []
        clause_regions = sido_names(raw) if guard_lifted else []
        if len(span_regions) >= 2 and "미상 시·도" not in span_regions and not re.search(r"및|과\s|와\s", region):
            # 값 구간에 시·도가 둘 이상 나열됐다 — 지역끼리의 대안이다("충청남도 또는 세종특별시").
            requirements.extend(
                item.model_copy(update={"scope": {**item.scope, "guard_basis": context.basis}})
                for item in _region_requirements(
                    raw, span_regions, notice_version_id=notice_version_id, key_prefix=key_prefix
                )
            )
            diagnostics.append({"code": "REGION_ALTERNATION", "raw": raw, "regions": list(span_regions)})
        elif len(clause_regions) >= 2:
            # 조항에는 시·도가 여럿인데 값 구간은 그것을 다 담지 않았다. 관계를 모르는 채로 하나만 확정하면
            # 다른 지역의 회사를 미달로 만든다.
            diagnostics.append({"code": "UNMAPPED_REGION", "raw": raw, "reason": "REGION_RELATION_UNCLEAR"})
        elif region:
            known = [name for name in span_regions if name != "미상 시·도"]
            add("REGION", "REGION", operator="MATCH", value=known[0] if len(span_regions) == 1 and known else region)
        else:
            diagnostics.append({"code": "UNMAPPED_REGION", "raw": raw})

    elif slot_type == "인력요건":
        headcount = slot.get("인원_norm") or {}
        role = (slot.get("인력역할_raw") or "").strip()
        if headcount.get("parse_status") == "success" and headcount.get("value") is not None:
            add(
                "STAFF",
                "STAFF",
                operator=headcount.get("op") or ">=",
                value=headcount.get("value"),
                unit=headcount.get("unit") or "PERSON",
                scope={"role": role} if role else {},
            )
        elif role:
            add("STAFF", "STAFF", operator="MATCH", value=role, scope={"role": role})
        else:
            diagnostics.append({"code": "UNMAPPED_STAFF", "raw": raw})

    elif slot_type in {"인증요건", "면허요건", "등록요건"}:
        name = (slot.get("등록인증_raw") or "").strip()
        issuer = (slot.get("발급기관_raw") or "").strip()
        kind = {
            "인증요건": "CERTIFICATION",
            "면허요건": "LICENSE",
            "등록요건": "REGISTRATION",
        }[slot_type]
        # [재현 2026-09-15] 등록요건뿐 아니라 인증·면허로 분류돼도 원문에 업종코드가 하나
        # 있으면 업종 요건일 수 있다. 실측에서 같은 "영업신고(업종코드 : 1450)" 조항을 모델이
        # 인증요건으로 낸 실행이 있었고, 그때 INDUSTRY 1450 이 아예 안 만들어져 인증 쪽에서
        # 미달이 났다.
        #
        # 단, **값이 업종명이나 등록 행위 모양일 때만**이다. "업종코드: 1468 업체는 ISO 27001
        # 인증 보유" 처럼 같은 조항에 진짜 인증이 적혀 있으면 그 인증은 별개 요건이다 —
        # 코드가 있다고 그것을 업종으로 바꾸면 ISO 27001 을 삼킨다(test_canonicalize 가 막는다).
        looks_like_industry = bool(name) and (
            _INDUSTRY_NAME_VALUE_RE.fullmatch(_squash_name(name))
            or _REGISTRATION_ACT_VALUE_RE.fullmatch(_squash_name(name))
        )
        size_alias = company_size_alias(name) if is_company_size_certificate_name(name) else None
        alternatives_built = lifted_name_alternatives(name) if not industry_codes and not size_alias else None
        if alternatives_built is not None:
            requirements.extend(alternatives_built)
        elif industry_codes and (slot_type == "등록요건" or looks_like_industry):
            add("INDUSTRY", "INDUSTRY", operator="MATCH", value=next(iter(industry_codes)), scope={"kind": kind, "industry_name": name})
        elif size_alias:
            # [재현 2026-09-15] "소기업·소상공인확인서" 는 인증이 아니라 회사 규모의 증빙 서류다.
            # 인증 요건으로 두면 회사 인증 목록과 대조돼 SMALL 회사가 미달을 받는다 —
            # 1450 업종/등록 이중분류와 같은 틀린 확정 경로. 골든셋은 COMPANY_SIZE 로 본다.
            add("COMPANY_SIZE", "COMPANY_SIZE", operator="MATCH", value=size_alias)
            diagnostics.append({
                "code": "COMPANY_SIZE_FROM_CERTIFICATE",
                "raw": raw,
                "certificate_name": name,
                "company_size": size_alias,
            })
        elif name:
            scope: dict[str, Any] = {"kind": kind}
            if issuer:
                scope["issuer"] = issuer
            add(
                "CERT",
                "REGISTRATION_CERTIFICATION",
                operator="MATCH",
                value=name,
                scope=scope,
            )
        else:
            diagnostics.append({"code": "UNMAPPED_REGISTRATION_CERTIFICATION", "raw": raw})

    elif slot_type == "기업규모요건":
        company_size = (slot.get("기업규모_raw") or "").strip()
        if company_size:
            # 이어 붙인 규모 낱말("중·소기업·소상공인")은 판정기의 alias 표에 없어 문자열
            # 비교로 떨어진다 — 합집합이 한 낱말과 같으면 그 낱말로 정규화한다(위 주석).
            add(
                "COMPANY_SIZE",
                "COMPANY_SIZE",
                operator="MATCH",
                value=company_size_alias(strip_size_restriction(company_size))
                or strip_size_restriction(company_size)
                or company_size,
                scope={"restriction": "EXCLUDE"}
                if _SIZE_EXCLUSION_RE.search(raw)
                else {},
            )
        else:
            diagnostics.append({"code": "UNMAPPED_COMPANY_SIZE", "raw": raw})

    elif slot_type == "기타요건":
        # [재현 2026-09-14] '기타요건' 은 통째로 버려졌다. 그런데 모델은 업종코드가 박힌
        # 조항을 '기타요건' 으로 분류하는 일이 잦다 — 구내식당 공고의 "영업신고(업종코드 :
        # 1450)를 하여 집단급식소 영업이 가능한 법인사업자" 가 그랬고, 골든셋은 이것을
        # INDUSTRY 1450 으로 본다. 분류는 실행마다 흔들려도 **원문의 숫자는 흔들리지 않는다.**
        # 그래서 코드가 직접 읽어 살린다.
        salvaged = salvage_closed_identifier(raw)
        if salvaged is None:
            diagnostics.append({"code": "UNMAPPED_REQUIREMENT", "raw": raw})
        else:
            salvaged_type, salvaged_value = salvaged
            add(salvaged_type, salvaged_type, operator="MATCH", value=salvaged_value)
            diagnostics.append({
                "code": "SALVAGED_CLOSED_IDENTIFIER",
                "raw": raw,
                "salvaged_type": salvaged_type,
                "value": salvaged_value,
            })
    else:
        diagnostics.append({"code": "UNKNOWN_LEGACY_TYPE", "type": slot_type, "raw": raw})

    return requirements, diagnostics


def _registration_alternation_requirements(
    raw: str,
    names: list[str],
    *,
    notice_version_id: str,
    key_prefix: str,
    industry_resolver: IndustryNameResolver | None,
    regions: list[str] | None = None,
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """대안 이름마다 원자 하나, 묶음은 ANY_OF. 지역 조건이 붙었으면 별도 묶음(AND)으로 하나 더. 업종 마스터에 정확히 있는 이름은 코드로 담는다.

    코드로 담긴 대안은 닫힌 비교(업종코드 일치)로 판정되고, 코드가 없는 이름은 등록·면허
    이름 비교로 판정된다 — 이름이 안 맞으면 미달이 아니라 확인 필요다. 묶음은 대안 중
    하나라도 **확정 충족**일 때만 충족이다.
    """
    group_key = f"{key_prefix}-GROUP"
    requirements: list[QualificationRequirement] = []
    resolved: dict[str, str] = {}
    for index, name in enumerate(names, start=1):
        code = industry_resolver.code_for(name) if industry_resolver is not None else None
        if code is not None:
            resolved[name] = code
        requirements.append(
            QualificationRequirement(
                requirement_key=f"{key_prefix}-ALT-{index}",
                requirement_group_key=group_key,
                group_operator="ANY_OF",
                notice_version_id=notice_version_id,
                type="INDUSTRY" if code is not None else "REGISTRATION_CERTIFICATION",
                operator="MATCH",
                value=code if code is not None else normalize_value_text(name, req_type="REGISTRATION_CERTIFICATION"),
                scope={"guard": GUARD_ASSESSED, **({"source_name": name} if code else {"kind": "REGISTRATION"})},
                condition_complexity="simple",
                raw=raw,
            )
        )
    if regions:
        requirements.extend(
            _region_requirements(raw, regions, notice_version_id=notice_version_id, key_prefix=key_prefix)
        )
    return requirements, [{
        "code": "REGISTRATION_ALTERNATION",
        "raw": raw,
        "names": list(names),
        "resolved_codes": resolved,
        **({"regions": list(regions)} if regions else {}),
    }]


def _region_requirements(
    raw: str, regions: list[str], *, notice_version_id: str, key_prefix: str
) -> list[QualificationRequirement]:
    """지역 하나면 단독 요건, 둘 이상이면 ANY_OF 묶음. 어느 쪽이든 다른 묶음과는 AND 다."""
    operator = "ANY_OF" if len(regions) > 1 else "ALL_OF"
    return [
        QualificationRequirement(
            requirement_key=f"{key_prefix}-REGION" + (f"-{index}" if len(regions) > 1 else ""),
            requirement_group_key=f"{key_prefix}-REGION-GROUP",
            group_operator=operator,
            notice_version_id=notice_version_id,
            type="REGION",
            operator="MATCH",
            value=region,
            scope={"guard": GUARD_ASSESSED},
            condition_complexity="simple",
            raw=raw,
        )
        for index, region in enumerate(regions, start=1)
    ]
