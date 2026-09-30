"""Shared deterministic source-clause safety screening.

[재현 — 2026-09-13, 홍규형 파일입니다. 아래 두 함수만 더했고 패턴 표는 그대로입니다]

가드가 걸러내는 것과 걸러내면 안 되는 것
----------------------------------------
이 가드는 복합·부정·예외 조건처럼 한 값으로 줄일 수 없는 조항을 UNKNOWN 으로
넘기려고 있다. 그런데 실제 제품 추출 결과에 대 보니 두 패턴이 **조항 자체가 아니라
그 주변 장식**에 걸리고 있었다.

  "「건설폐기물의 재활용촉진에 관한 법률」 제21조에 따른 건설폐기물중간처리업
   (업종코드 : 1253)을 등록한 업체"
      -> LEGAL_PROCEDURAL_RULE ('법률' 이 있어서). 판정은 업종코드 1253 보유 여부로
         단순하다. 법령 인용은 근거 표시이지 절차 규정이 아니다.

  "본점소재지(개인사업자인 경우 사업자등록증 또는 허가 … 서류가 기재된 사업장의
   소재지)를 전남광주통합특별시에 소재한 업체"
      -> ALTERNATIVE_OR_EXCEPTION_RULE ('또는' 이 있어서). 그 '또는' 은 괄호 안에서
         어느 서류로 주소를 보는지를 설명할 뿐이고, 요건은 '전남광주 소재' 하나다.

한국 공고는 업종 요건에 근거 법령을 자주 붙이므로 첫째는 정상적인 업종 요건까지
막을 수 있다. canonical raw 가 법령 인용을 뗀 형태라면 골든 러너에서도 이 제품 경로
실패가 드러나지 않는다.

그래서 패턴을 대기 전에 **장식을 벗긴다.** 「…」 로 감싼 법령명, 제N조·제N항 같은
조문 번호, 괄호 안 설명을 지운 뒤 같은 패턴을 적용한다. 패턴 표 자체는 손대지 않는다
— 무엇이 위험한 조항인지에 대한 판단은 바뀌지 않았고, 그 판단을 조항이 아닌 곳에
적용하던 것만 고친다.

효과는 골든 러너로 잰다. 잘못된 확정이 0 으로 유지되면서 안전한 보류가 줄어야 한다.
"""

from __future__ import annotations

import re

_COMPLEX_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"〃|상동", "UNRESOLVED_TABLE_REFERENCE"),
    (r"공동수급|공동계약|구성원|대표사|분담이행|공동이행", "COMPOSITE_PARTY_RULE"),
    (r"대표자.*(동일|중복)|중복.*대표자|대표자.*변경등록", "REPRESENTATIVE_CONFLICT_RULE"),
    (r"\b또는\b|\b다만\b|각\s*호|중\s*하나|어느\s*하나", "ALTERNATIVE_OR_EXCEPTION_RULE"),
    (r"관계\s*법령|시행규칙|법률|규정에\s*따라|입찰무효", "LEGAL_PROCEDURAL_RULE"),
    (r"아니어야|하지\s*않아야|아닌\s*자|제외한다|제외됨", "NEGATED_RULE"),
    (r"계약.*해지|낙찰자.*결정|제한을\s*받는", "POST_AWARD_OR_RESTRICTION_RULE"),
)

# [재현 2026-09-15, 검수에서 재현] 나라장터(국가종합전자조달시스템) 입찰참가자격등록·전자입찰
# 이용자 등록은 모든 입찰자가 거치는 절차이지 회사 프로필과 대조할 자격이 아니다. 골든셋도
# 요건으로 보지 않는다.
#
# 09-15 첫 수정 때 이 패턴을 `_COMPLEX_PATTERNS`(stripped 텍스트 대상)에 넣었는데, 실제
# 01634263-003 문구 "「국가종합전자조달시스템 입찰참가자격등록규정」에 따라 …" 로 검수하니
# 다시 4/5 실행에서 REGISTRATION_CERTIFICATION 유령이 살아났다. 원인은 순서였다 —
# `strip_decorations` 가 「…규정」+"에 따라" 를 정확히 법령 인용으로 보고 먼저 지워버려서,
# '국가종합전자조달시스템' 이라는 글자 자체가 패턴이 돌기 전에 이미 없어져 있었다. 이 규정은
# 인용이 곧 요건 전문이라 다른 조항의 "근거 법령 인용" 과 다르다 — 지우면 안 되는 인용이다.
# 그래서 decoration 을 벗기기 전, 원문 그대로에 먼저 이 패턴을 댄다.
#
# [골든 17개 실측 2026-09-15] 실제 공고는 시스템을 "조달청" 이라고도 부르고("조달청에
# 입찰참가자격등록을 한 자", "조달청 전자입찰 이용자등록한 업체"), 목적격 조사를 끼워
# "입찰참가자격**을** 등록한 업체" 라고도 쓴다. 넷 다 같은 절차다. 3/3 으로 고정된 유령이
# 두 공고(01697220·01706001)에 있었고 1/3 흔들림이 둘 더 있었다.
_NARA_MARKET_PROCEDURAL_RE = re.compile(
    r"(?:국가종합전자조달시스템|나라장터|G2B)"
    # "나라장터에 아래 업종 중 해당 자격을 등록한 업체" — 코드 항목들의 우산 문장(J14 1/3 유령).
    # 코드는 각자 줄에서 따로 살아나므로 우산은 절차로 보내는 게 맞다.
    r".{0,20}?(?:(?:입찰\s*참가\s*)?자격\s*(?:을|를)?\s*등록|이용자\s*등록|입찰참가등록|에\s*등록)"
    # '조달청' 은 "조달청 우수제품에 등록" 같은 진짜 자격도 수식하므로 막연한 "에 등록" 은
    # 빼고 절차 이름이 분명한 모양만 잡는다.
    r"|조달청.{0,20}?(?:입찰\s*참가\s*자격\s*(?:을|를)?\s*등록|전자\s*입찰\s*이용자\s*등록|입찰참가등록)"
    r"|입찰\s*참가\s*자격\s*등록\s*규정"
    # 시스템명이 어느 필드에도 없는 맨 형태 — "입찰참가등록 마감일시까지 입찰참가자격을 등록한
    # 업체"(우치공원 1/3 재발). "입찰참가자격을 등록한 업체"는 나라장터 절차 말고 다른 뜻이
    # 없다. 완료형(등록한·등록을 필한·마친)만 잡는다 — "등록을 하여야 한다"·"하지 않아야" 같은
    # 문장은 공동수급·부정 가드가 먼저 볼 몫이고, 제목("3. 입찰참가자격")엔 '등록'이 없다.
    r"|입찰\s*참가\s*자격\s*(?:을|를)?\s*등록(?:을\s*)?(?:한|필한|마친|완료한)"
    r"|전자\s*입찰\s*이용자\s*등록(?:을\s*)?(?:한|필한|마친|완료한)"
    # 전자입찰 접속용 인증서 — "지정 전자서명인증자로부터 발급받은 사업자용 인증서를 이용하여
    # 전자조달시스템에 접속"(우치공원 1/5 유령). 회사가 갖출 자격이 아니라 입찰 절차다.
    r"|(?:사업자용|공인|전자\s*입찰용)\s*인증서"
)

# 조항의 뜻과 무관한 장식. 법령명 인용, 조문 번호, 주소 증빙 설명 괄호.
#
# 따옴표는 두 조건을 다 만족할 때만 벗긴다 — 안이 법령명 꼴이고, 바로 뒤에 인용 문맥
# (제N조 · 에 따른 · 에 의거 …)이 붙을 때. 「…」 는 법령 인용에 쓰이지만 조건을 감싸는
# 데도 쓰인다. 「소기업 또는 소상공인」 을 지우면 '또는' 이 가드에 닿기 전에 사라지고
# (#128 1차 리뷰), '기준' 을 법령 접미로 두면 「소기업 또는 소상공인 기준」 도 지워진다
# (2차 리뷰). 접미 하나로는 못 가르므로 뒤따르는 인용 문맥까지 요구한다.
_QUOTED_RE = re.compile(
    r"(?:「(?P<a>[^」]*)」|『(?P<b>[^』]*)』)"
    r"(?P<ctx>\s*(?:(?:시행령|시행규칙|같은\s*법)?\s*제\s*\d+\s*(?:조|장)"
    r"|에\s*(?:따른|따라|의한|의하여|의거한?|근거한?)|상\b|에서\s*정한))?"
)
_STATUTE_NAME_RE = re.compile(
    r"(?:에\s*관한\s*법률|법률|법|시행령|시행규칙|규칙|조례|규정|고시|지침|예규|훈령)\s*$"
)
_ARTICLE_REF_RE = re.compile(
    r"(?:같은\s*법\s*)?(?:시행령|시행규칙)?\s*제\s*\d+\s*조(?:의\s*\d+)?(?:\s*제\s*\d+\s*항)?(?:\s*제\s*\d+\s*호)?"
    r"(?:\s*\[별표\s*\d*\])?\s*(?:에\s*(?:따른|의한|따라|의거한?)|의)?"
)
_PARENTHETICAL_RE = re.compile(r"\((?P<ascii>[^()]*)\)|（(?P<fullwidth>[^（）]*)）")
# 괄호는 기본 보존한다. 주소를 어느 서류로 보는지 나열한 설명 괄호만 벗긴다.
# "사업자등록증 또는 허가 서류" 만으로는 부족하다 — "(사업자등록증 또는 허가 서류 제출)"
# 은 실제 대안 제출 조건이라 '또는' 이 가드에 남아야 한다 (#128 2차 리뷰). 주소 설명은
# 반드시 '사업장' 과 '소재지' 를 함께 말하므로 그 둘을 요구한다.
_ADDRESS_EVIDENCE_OR_RE = re.compile(
    r"(?:사업자등록증|법인등기부(?:등본)?)\s*또는\s*"
    r"(?:허가|인가|면허|등록|신고)[^()]*사업장[^()]*소재지"
)


def _strip_quoted(match: re.Match[str]) -> str:
    inner = (match.group("a") or match.group("b") or "").strip()
    if _STATUTE_NAME_RE.search(inner) and match.group("ctx"):
        return " "
    return match.group(0)


def _strip_parenthetical(match: re.Match[str]) -> str:
    inner = match.group("ascii") or match.group("fullwidth") or ""
    return " " if _ADDRESS_EVIDENCE_OR_RE.search(inner) else match.group(0)


def strip_decorations(raw: str) -> str:
    """법령명 인용·조문 번호·주소 증빙 설명 괄호를 벗긴 본문. 가드는 이것을 본다.

    벗기는 것은 셋뿐이고 나머지는 전부 남긴다. 조건을 감싼 따옴표, 제한을 적은 괄호가
    사라지면 가드가 우회되므로, 무엇을 지울지가 아니라 무엇만 지울지를 정한다.
    """
    text = _QUOTED_RE.sub(_strip_quoted, raw)
    text = _ARTICLE_REF_RE.sub(" ", text)
    text = _PARENTHETICAL_RE.sub(_strip_parenthetical, text)
    return " ".join(text.split())


# 업종코드가 문장에 박혀 있다는 표시 — "업종코드 : 1468", "폐기물수집·운반업(1227)",
# "기타자유업(행사대행업)(9901)". 사람이 달리 쓸 수 없는 닫힌 식별자다.
_INDUSTRY_CODE_HINT_RE = re.compile(
    r"업종\s*코드\s*[:：]?\s*[0-9]{4}(?![0-9])"
    r"|업\s*\)?\s*\(\s*[0-9]{4}\s*\)"
)


def unsafe_clause_reason(raw: str) -> str | None:
    """Share conservative source-clause screening with mapping and rules.

    [재현 2026-09-15, 골든 17개 실측] 절차 문구와 진짜 업종 요건이 **한 문장**에 같이 오는
    공고가 있다 —

        "소프트웨어사업자(컴퓨터관련서비스사업[업종코드:1468])로 등록을 필한 업체로
         나라장터에 입찰참가자격을 등록한 업체"                       (01635124)
        "국가종합전자조달시스템입찰참가자격등록규정에 따라 … 나라장터(G2B시스템)에
         아래의 사항을 입찰참가자격으로 등록한 자 -[기타자유업(행사대행업)(9901)]…" (01684825, J20)

    절차 가드가 문장 전체를 막으면 골든이 기대하는 INDUSTRY 1468·9901 이 사라진다(실제로
    사라졌다). 업종코드는 닫힌 식별자라 그 문장의 요건이 무엇인지 코드가 확신할 수 있다 —
    **코드가 있으면 절차 문구(LEGAL_PROCEDURAL_RULE)는 무시한다.** 논리를 바꾸는 가드
    (또는·다만·부정·공동수급)는 코드가 있어도 그대로 건다.
    """
    # 코드는 공백을 다 걷어낸 본문에서 읽는다 — 원문은 "[업⏎종코드: 5898]" 처럼 낱말 안에서도
    # 줄을 바꾼다(골든 01688607).
    has_code = bool(_INDUSTRY_CODE_HINT_RE.search(re.sub(r"\s+", "", raw or "")))
    # 나라장터 등록 규정은 인용(「…」)이 곧 요건 전문이다 — 벗기기 전에 원문(줄바꿈만
    # 접어서)으로 먼저 검사한다. 벗긴 뒤 검사하면 규정명 자체가 지워져 못 잡는다.
    collapsed_raw = " ".join((raw or "").split())
    if not has_code and _NARA_MARKET_PROCEDURAL_RE.search(collapsed_raw):
        return "LEGAL_PROCEDURAL_RULE"
    text = strip_decorations(raw)
    for pattern, code in _COMPLEX_PATTERNS:
        if code == "LEGAL_PROCEDURAL_RULE" and has_code:
            continue
        if re.search(pattern, text):
            return code
    return None


# ---------------------------------------------------------------------------
# 구조를 보는 가드
#
# [2026-09-15] 이번 주 흔들림의 뿌리 하나는 가드가 **문장 단위 이분법**이었다는 것이다.
# 실제 공고는 절차 문구·예외·진짜 요건을 한 문장에 섞어 쓰는데, 문장째 막거나 통과시키니
# 진짜 요건(9901·1468)을 잃거나 유령을 들여보내거나 둘 중 하나였다. 그리고 같은 가드가
# 판정기에서 raw 를 **두 번째로** 읽어, 추출이 ANY_OF 로 담아 둔 대안 묶음을 "또는이 있네"
# 하고 다시 막았다(J14 — 1257 보유 회사가 적합이 아니라 확인 필요).
#
# 원칙: 가드는 raw 문장에 묻지 않고 **추출이 이미 만든 구조**에 묻는다 — 닫힌 식별자가
# 있는가, 대안이 ANY_OF 로 담겼는가, 예외 단서는 원문에서 코드가 판단했는가. raw 는 사람이
# 읽을 근거이지 판단의 입력이 아니다.
#
# 우선순위(코드로 박는다):
#   1. 예외 단서가 원문 청크에서 확인된 원자        → ABSTAIN (composite)
#   2. 닫힌 식별자가 있으면 절차 문구는 무시           (unsafe_clause_reason 가 이미 그렇게 한다)
#   3. ANY_OF 로 담긴 원자의 '또는' 은 이미 소화된 것 → 대안 사유는 무시
#   4. 남은 논리어(다만·제외·부정·공동수급·미해결 표) → ABSTAIN (composite)
#   5. 코드 없는 절차 문구                            → PROCEDURAL
#   6. 그 외                                          → KEEP (simple)
#
# 결과는 요건에 새긴다(condition_complexity, scope.guard). 판정기·askability 는 그 표시가
# 있는 요건에 대해 raw 를 다시 읽지 않는다. 표시가 없는 요건(예전 저장 행, 골든 고정본)은
# 예전처럼 raw 를 본다 — 그래서 골든 회귀는 이 변경으로 움직이지 않는다.
# ---------------------------------------------------------------------------

GUARD_ASSESSED = "assessed"
GUARD_REASON_EXCEPTION = "EXCEPTION_UNRESOLVED"


class ClauseAssessment:
    __slots__ = ("verdict", "reason", "complexity")

    def __init__(self, verdict: str, reason: str | None, complexity: str) -> None:
        self.verdict = verdict          # KEEP | ABSTAIN | PROCEDURAL
        self.reason = reason
        self.complexity = complexity    # simple | composite

    def __repr__(self) -> str:  # pragma: no cover - 디버그용
        return f"ClauseAssessment({self.verdict}, {self.reason}, {self.complexity})"


def assess_clause(
    raw: str,
    *,
    group_operator: str | None = "ALL_OF",
    exception_unresolved: bool = False,
) -> ClauseAssessment:
    """원자 하나를 구조 기준으로 평가한다. 위 우선순위 그대로."""
    if exception_unresolved:
        return ClauseAssessment("ABSTAIN", GUARD_REASON_EXCEPTION, "composite")
    reason = unsafe_clause_reason(raw)
    if reason is None:
        return ClauseAssessment("KEEP", None, "simple")
    if reason == "ALTERNATIVE_OR_EXCEPTION_RULE" and group_operator == "ANY_OF":
        # '또는' 은 ANY_OF 로 이미 구조가 됐다. 대안을 열 때(industry_code_alternation) 예외
        # 낱말이 있으면 열지 않으므로, 여기 도달한 ANY_OF 원자의 사유는 소화된 '또는' 뿐이다.
        return ClauseAssessment("KEEP", None, "simple")
    if reason == "LEGAL_PROCEDURAL_RULE":
        return ClauseAssessment("PROCEDURAL", reason, "simple")
    return ClauseAssessment("ABSTAIN", reason, "composite")


def is_guard_assessed(scope: dict | None) -> bool:
    return bool(scope) and scope.get("guard") == GUARD_ASSESSED
