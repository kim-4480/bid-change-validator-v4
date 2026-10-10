"""낱말 가드를 맥락에 따라 푼다 — 조항의 극성(clause_polarity)이 붙은 슬롯에만 적용한다.

clause_safety 의 가드는 조항에 '또는'·'다만'·'아닌 자' 가 있으면 조항을 통째로 뺀다. 여기서는 그 가운데
**낱말만으로는 뜻을 알 수 없는 사유**(SOFT_REASONS)를, 모델이 읽은 극성으로 다시 판단한다.

    극성이 없다                    → DEFAULT  (예전 가드 그대로. 극성 기능을 켜지 않은 경로)
    극성이 POSITIVE 가 아니다      → ABSTAIN  (배제·예외·요건 아님·모름 — 확인 필요)
    POSITIVE 인데 부정 낱말이 있다 → ABSTAIN  (모델과 낱말 규칙의 이견 — 확인 필요)
    POSITIVE 이고 남은 사유가 SOFT → KEEP     (가드를 푼다)
    POSITIVE 이지만 다른 사유가 있다 → DEFAULT (공동수급·대표자 중복·표 참조·절차 문구는 예전대로)

낱말 규칙은 혼자서 조항을 버리지 않는다. 모델이 요구라고 읽은 조항을 한 번 더 의심하는 데만 쓴다. 틀렸을 때의
비용이 한쪽으로 기울기 때문이다 — 배제를 요구로 확정하면 틀린 판정이고, 요구를 확인 필요로 두면 사람이 한 번 더
볼 뿐이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from bidengine.judgment.clause_safety import guard_reasons, strip_decorations

# 낱말만 보고는 대안인지 부연인지, 배제인지 결격 확인인지 알 수 없는 사유.
SOFT_REASONS = frozenset({"ALTERNATIVE_OR_EXCEPTION_RULE", "NEGATED_RULE", "POST_AWARD_OR_RESTRICTION_RULE"})

# 모델이 POSITIVE 라고 해도 이 낱말이 조항(장식을 벗긴)에 있으면 확정하지 않는다.
_NEGATION_VETO_RE = re.compile(
    r"아니어야|하지\s*않아야|아닌\s*자|아니한\s*자|제외"
    r"|참[가여]할\s*수\s*없|입찰에\s*참[가여]할\s*수\s*없"
    r"|참[가여]\s*(?:를|을)?\s*(?:제한|불가|배제|금지)|불허|허용(?:하지|되지)\s*않"
)


@dataclass(frozen=True)
class ContextDecision:
    action: str               # KEEP | ABSTAIN | DEFAULT
    reason: str | None = None  # ABSTAIN 사유
    basis: str | None = None   # KEEP 일 때 무엇으로 정했나: "code"(걸린 사유 없음) | "model_polarity"(가드를 풂)


def decide(
    text: str, polarity: str | None, *, exclusion_representable: bool = False, closed_value: bool = False
) -> ContextDecision:
    """text: 가드가 보는 글(조항 원문, 필요하면 등록 이름 필드를 덧붙인 것).

    exclusion_representable: 이 슬롯의 배제를 구조로 담을 수 있는가(기업 규모의 참여 제한).
    closed_value: 값이 닫힌 어휘로 확인됐는가(값 구간에 사전에 있는 지역 이름). 업종코드가 있을 때처럼
    법령 인용 낱말("법률", "시행규칙")의 절차 가드를 풀어도 된다 — "…법률 시행령 제13조의 자격을 갖추고,
    … 본점 소재지가 전주시인 업체" 의 전주시 요건이 절차 문구로 소리 없이 사라졌다(2026-10-06 세 번째 표본).
    """
    if polarity is None:
        return ContextDecision("DEFAULT")
    reasons = guard_reasons(text)
    if "COMPOSITE_PARTY_RULE" in reasons:
        # 공동수급·공동계약 조건은 모델이 뭐라고 읽든 확인 필요다. '요건 아님' 으로 읽히면 절차 조항이 되어
        # 사람이 볼 자리에서 사라진다(2026-10-03 표본 R26BK01736181 "공동수급 및 하도급을 불허").
        return ContextDecision("DEFAULT")
    hard = [reason for reason in reasons if reason not in SOFT_REASONS]
    if closed_value and polarity == "POSITIVE":
        hard = [reason for reason in hard if reason != "LEGAL_PROCEDURAL_RULE"]
    if polarity == "EXCLUSION" and exclusion_representable and not hard:
        return ContextDecision("KEEP", basis="model_polarity")
    if polarity != "POSITIVE":
        return ContextDecision("ABSTAIN", reason=f"MODEL_POLARITY_{polarity}")
    if _NEGATION_VETO_RE.search(strip_decorations(text)):
        return ContextDecision("ABSTAIN", reason="POLARITY_DISAGREEMENT")
    if hard:
        return ContextDecision("DEFAULT")
    return ContextDecision("KEEP", basis="model_polarity" if reasons else "code")
