"""Vocabulary parts for clause detection — matching sentence *shape*, not sentences.

A regex written against a whole sentence only ever fires on that sentence. Instead
this module keeps the meaning-bearing parts of a clause (who, what verb, what
object, what qualifier) as separate synonym lists, and the rules compose patterns
out of them. Adding one synonym to a part widens every pattern that uses it.

    "기타 발주기관이 요구하는 사항" and "상기 외 감독관이 지시하는 제반 사항"
    are the same shape: [residual][authority][discretion verb][open object].

Composing four parts catches both instead of memorising two sentences.

Judgment remains code. No model participates in anything here.
"""

from __future__ import annotations

import re


def alt(items: list[str]) -> str:
    """Join parts into one non-capturing alternation."""
    return "(?:" + "|".join(items) + ")"


# Particles that may follow a noun. Without this boundary "업무" matches inside
# "업무상의 정보": another Hangul syllable following means it is a different word.
_PARTICLE = r"(?:[을를은는이가의에와과도만]|으?로|까지|부터|에서|이나|나)?(?![가-힣])"


def noun_alt(items: list[str]) -> str:
    """Join noun parts, carrying the particle boundary."""
    return "(?:" + "|".join(items) + ")" + _PARTICLE


# ── who: any way of naming the contracting authority ─────────────────────
AUTHORITY = [
    r"발주\s*(?:기관|처|자|청|부서)",
    r"수요\s*기관",
    r"주무\s*관청",
    r"소관\s*부서",
    r"감독\s*(?:관|원)",
    r"계약\s*담당\s*(?:공무원|자)?",
    r"공사",
    r"공단",
    r"공단측",
    r"위탁\s*기관",
    # A following Hangul syllable means a different word ("본 사" vs "본 사업").
    r"본\s*(?:기관|원|사|청)(?![가-힣])",
    r"당\s*(?:기관|원|사|청)(?![가-힣])",
    r"甲",
    r"갑(?=[에이은가측])",
    r"담당\s*(?:부서|자|공무원)",
]
AUTHORITY_RE = alt(AUTHORITY)

# ── residual pointer: "everything other than what is listed" ─────────────
RESIDUAL = [
    r"기타",
    r"그\s*밖(?:에|의|으로)?",
    r"그밖(?:에|의)?",
    r"이\s*외(?:에|의)?",
    r"이외(?:에|의)?",
    r"그\s*외(?:에|의)?",
    r"그외(?:에|의)?",
    r"상기\s*외",
    r"위\s*외",
    r"전기\s*외",
    r"이와\s*관련(?:된|하여|하는)",
    r"추가(?:적)?으?로",
]
RESIDUAL_RE = alt(RESIDUAL)

# ── discretion verbs: the authority decides the scope ────────────────────
DISCRETION_VERB = [
    r"필요하다고\s*인정(?:하는|하여|되는|하면)",
    r"인정하는",
    r"요구하는",
    r"지시하는",
    r"요청하는",
    r"지정하는",
    r"판단하는",
    r"정하는",
    r"결정하는",
    r"명하는",
    r"제시하는",
    r"부여하는",
]
DISCRETION_RE = alt(DISCRETION_VERB)

# ── open objects: an object that does not close the scope ────────────────
OPEN_OBJECT = [
    r"제반\s*사항",
    r"모든\s*것",
    r"일체",
    r"사항",
    r"업무",
    r"과업",
    r"내용",
    r"작업",
    r"용역",
    r"임무",
]
OPEN_OBJECT_RE = noun_alt(OPEN_OBJECT)

# Nouns that actually denote work scope. "일체" and "모든 것" are excluded here
# because legal boilerplate like "손해배상 등 일체의 민·형사상 책임" would match.
SCOPE_OBJECT = [r"사항", r"업무", r"과업", r"작업", r"용역", r"임무", r"내용"]
SCOPE_OBJECT_RE = noun_alt(SCOPE_OBJECT)

# ── ancillary wording: opens the scope without a residual pointer ────────
# '관련' is excluded: it is far too common in ordinary documents to be a signal.
ANCILLARY = [r"부수", r"수반", r"파생", r"연관"]
ANCILLARY_RE = alt(ANCILLARY)

# ── deferral: decided later, or by consultation ──────────────────────────
DEFERRAL = [r"협의(?:하여|를\s*통해|후|\s*후)", r"추후", r"별도(?:로)?", r"차후", r"향후"]
DEFERRAL_RE = alt(DEFERRAL)
DEFERRAL_VERB = alt(
    [r"정하는", r"정한다", r"결정(?:하는|한다|된다)", r"협의한다", r"협의하여\s*정"]
)

# ── intellectual property parts ──────────────────────────────────────────
IP_NOUN = [
    r"저작재산권",
    r"저작인격권",
    r"저작권",
    r"지식재산권",
    r"지적재산권",
    r"산업재산권",
    r"소유권",
    r"실시권",
    r"권리",
]
IP_NOUN_RE = alt(IP_NOUN)

PRODUCT = [
    r"산출물",
    r"결과물",
    r"성과물",
    r"계약\s*목적물",
    r"납품물",
    r"개발물",
    r"제작물",
    r"용역\s*목적물",
]
PRODUCT_RE = alt(PRODUCT)

# Predicates meaning sole vesting — not only vesting/owning but also
# holding, transferring and assigning.
SOLE_VERB = [r"귀속", r"소유", r"보유", r"이전", r"양도", r"이관", r"승계", r"취득"]
SOLE_VERB_RE = alt(SOLE_VERB)

# Wording that matches the standard (joint ownership, equal shares). Its presence
# means the sentence is not a sole-vesting clause.
JOINT_OWNERSHIP = [
    r"공동\s*(?:으로\s*)?(?:소유|귀속|보유|개발)",
    r"공유(?:한다|하며|하고|로\s*한다)?",
    r"지분[은이]?\s*균등",
    r"균등한?\s*지분",
    r"지분을?\s*균등",
    r"양\s*당사자가?\s*(?:균등|공동)",
    r"각각\s*100분의\s*50",
    r"각\s*50%",
    # Declaring that the standard terms govern also counts as compliant.
    # "따른다" does not contain "따르", so every inflection has to be listed.
    r"(?:용역계약일반조건|계약예규|국가계약법)[^.\n]{0,40}(?:따르|따른|따라|준용|의하|의한)",
]
JOINT_OWNERSHIP_RE = alt(JOINT_OWNERSHIP)

# ── defect liability parts ───────────────────────────────────────────────
DEFECT_NOUN = alt([r"하자", r"결함", r"瑕疵", r"불량"])
REPAIR_NOUN = alt([r"보수", r"담보", r"책임", r"수정", r"보증(?!금)"])
FREE_MAINT = alt([r"무상\s*(?:유지\s*)?(?:보수|관리)", r"무상\s*하자", r"무상으?로?"])

# ── liquidated damages parts ─────────────────────────────────────────────
DELAY_PENALTY_RE = alt(
    [r"지체\s*(?:상금|배상금|보상금)", r"지연\s*(?:배상금|손해금|상금|보상금)"]
)

# ── decrease wording (termination trigger) ───────────────────────────────
DECREASE_RE = alt(
    [r"감소", r"축소", r"삭감", r"감액", r"줄어", r"줄인", r"줄이", r"감축", r"저감", r"하향"]
)

# ── termination wording ──────────────────────────────────────────────────
TERMINATION_RE = alt([r"해지", r"해제", r"해약", r"계약\s*종료"])

# ── inspection wording ───────────────────────────────────────────────────
INSPECTION_RE = alt([r"검사", r"검수", r"인수\s*검사", r"완료\s*검사", r"납품\s*검사"])

# ── payment parts ────────────────────────────────────────────────────────
# "계약금액" is deliberately absent: it names a sum in almost every contract
# clause, so including it would pull unrelated figures into this rule.
PAYMENT_NOUN_RE = alt(
    [r"기성\s*(?:대가|금|부분금)", r"대가", r"대금", r"용역\s*비", r"용역\s*대금", r"보수금"]
)
PAYMENT_VERB_RE = alt([r"지급", r"지불", r"청구", r"결제", r"정산"])

# ── damages parts ────────────────────────────────────────────────────────
DAMAGE_NOUN_RE = alt([r"손해\s*배상", r"손해", r"손실", r"피해", r"배상"])
BEAR_VERB_RE = alt([r"부담", r"배상", r"보상", r"변상", r"책임(?:을|이|은)?\s*(?:진다|부담|있)"])

# The 예규 draws the line at fault: harm the contractor is not responsible for
# falls to the authority (제23조제1항 단서), as does harm to a delivered object
# (제2항). Wording that keeps either is compliant.
FAULT_CARVE_OUT_RE = alt(
    [
        r"책임\s*없는\s*사유",
        r"책임없는\s*사유",
        r"귀책\s*사유가?\s*없",
        r"귀책\s*사유로\s*인한\s*경우에\s*한",
        r"계약상대자의?\s*(?:책임|귀책)[^.\n]{0,10}?(?:아닌|없)",
        r"발주\s*(?:기관|처|자)[^.\n]{0,8}?부담",
        # Declaring that the standard terms govern also counts as compliant.
        # "따른다" does not contain "따르", so every inflection has to be listed.
    r"(?:용역계약일반조건|계약예규|국가계약법)[^.\n]{0,40}(?:따르|따른|따라|준용|의하|의한)",
    ]
)

# Wording that erases that line — liability without regard to fault, or for
# everything without limit.
NO_FAULT_LIABILITY_RE = alt(
    [
        r"귀책\s*사유(?:를|에)?\s*불문",
        r"책임\s*(?:의\s*)?유무(?:를|에)?\s*불문",
        r"고의[·,\s]*과실(?:의\s*)?(?:유무|여부)?(?:를|에)?\s*불문",
        r"사유(?:를|에)?\s*불문하고[^.\n]{0,20}?(?:배상|부담)",
        r"일체의?\s*(?:손해|손실|책임|배상)",
        r"모든\s*(?:손해|손실|책임)",
        r"여하한?\s*(?:손해|책임)",
        r"무한\s*(?:책임|배상)",
        r"전적으?로?\s*(?:책임|부담)",
        r"제한\s*없이\s*(?:배상|부담)",
    ]
)


def compile_forms(*patterns: str) -> list[re.Pattern[str]]:
    return [re.compile(pattern) for pattern in patterns]
