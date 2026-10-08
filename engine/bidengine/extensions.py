"""Notice-specific profile extensions — information collected only on demand.

The core profile (`app.ai.profile`) is industry-neutral by design. This service
reviews service, construction, goods and research notices through one pipeline,
so the sign-up form cannot carry every industry's vocabulary.

Some requirements still cannot be judged from core fields. "특급기술자 2인 이상" needs
a software engineer grade, which the core `staff` section deliberately does not
have. Two tempting answers are both wrong:

1. Add `grade` to core staff — that pushes software vocabulary onto construction
   companies at sign-up.
2. Derive the grade from career years — that decides a requirement without the
   grading rule as a source, which this project does not do.

The third way is what lives here: leave the core alone, and ask for the extra
field only when a notice actually requires it.

    required_for(requirements)  -> what this notice needs beyond the core
    profile.extensions[key]     -> the collected answer, if we already have it
    spec.judge(value, req)      -> deterministic judgment on that answer

Adding support for another industry means adding one entry to `EXTENSION_SPECS`.
Every function here is plain code; the LLM is not involved in any of it.

제품 연결 현황 — 이 모듈은 판정까지만 지원한다
------------------------------------------------
`profile.extensions` 를 채우는 경로는 아직 비어 있다. 세 자리가 남아 있다:

1. 수집 — `app.qualification.ask_back` 가 `required_for()` 로 질문을 만들어야 한다.
2. 저장 — 답변을 `company_sw_engineer_grades` 행과 `companies.conglomerate_affiliate`
   컬럼에 써야 한다. 표는 migration 010 으로 이미 있고, ORM 모델이 없다.
3. 적재 — `build_company_profile_snapshot()` 이 그 값을 `extensions` 로 실어야 한다.

세 자리가 비어 있는 동안 제품에서 이 요건을 만나면 결과는 항상 UNKNOWN(확인 불가)
이다. 조용히 '충족'으로 새지 않는다는 뜻이므로 안전한 상태이고,
`test_product_profile_path_cannot_answer_an_extension_yet` 이 그 상태를 고정한다.
연결이 끝나면 그 테스트가 깨지는 것이 신호다.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from bidengine.contracts import QualificationRequirement
from bidengine.normalization import normalize_count


@dataclass(frozen=True)
class ExtensionSpec:
    """One optional profile field, plus how to detect, collect and judge it."""

    key: str
    label: str
    domain: str
    why: str
    ask: str
    input_hint: str
    detect: Callable[[QualificationRequirement], bool]
    parse: Callable[[str], Any]
    judge: Callable[[Any, QualificationRequirement], tuple[str | None, str]]
    # Empty means the extension applies regardless of requirement type.
    requirement_types: tuple[str, ...] = ()
    # Some requirements are detected here but judged by a core rule that has to
    # weigh this answer together with a core field. Those return False.
    owns_judgment: Callable[[QualificationRequirement], bool] | None = None
    aliases: tuple[str, ...] = field(default=())


# ── software engineer grade ──────────────────────────────────────────────
_SW_GRADE_REQ_RE = re.compile(r"(특급|고급|중급|초급)[^.\n]{0,10}?(\d+\s*[인명])")
_SW_GRADE_PAIR_RE = re.compile(r"(특급|고급|중급|초급)\s*(?:기술자)?\s*[:\s]*(\d+)\s*[인명]?")
_SW_GRADE_ORDER = ("초급", "중급", "고급", "특급")


def _sw_grade_detect(requirement: QualificationRequirement) -> bool:
    return bool(_SW_GRADE_REQ_RE.search(requirement.raw or ""))


def _sw_grade_parse(answer_text: str) -> dict[str, int] | None:
    """'특급 2명, 고급 3명' -> {'특급': 2, '고급': 3}, or None when nothing parses.

    A fixed-shape answer like this is read by code rather than by the model: it is
    more accurate and cheaper. The LLM is only used to turn free prose into
    structured fields.
    """
    found: dict[str, int] = {}
    for match in _SW_GRADE_PAIR_RE.finditer(answer_text or ""):
        grade, count = match.group(1), match.group(2)
        normalized = normalize_count(f"{count}명")
        if normalized["parse_status"] == "success":
            found[grade] = int(normalized["value"])
    return found or None


def _sw_grade_judge(
    value: Any, requirement: QualificationRequirement
) -> tuple[str | None, str]:
    match = _SW_GRADE_REQ_RE.search(requirement.raw or "")
    if not match:
        return None, "요건에서 등급·인원을 특정하지 못함"
    if not isinstance(value, dict):
        return None, "등급별 인원 형식을 읽지 못함"

    need_grade = match.group(1)
    normalized = normalize_count(match.group(2))
    if normalized["parse_status"] != "success":
        return None, "요건 인원 수를 읽지 못함"
    need = normalized["value"]

    have = value.get(need_grade)
    if have is None:
        return None, f"'{need_grade}' 등급 인원을 아직 받지 못함"
    if have >= need:
        return "충족", f"{need_grade} 보유 {have}인 ≥ 요구 {need}인"

    # Whether a higher grade satisfies a lower-grade requirement is a rule we do
    # not have the source text for, so it is reported, not assumed.
    index = _SW_GRADE_ORDER.index(need_grade)
    upper = {
        grade: value[grade] for grade in _SW_GRADE_ORDER[index + 1 :] if value.get(grade)
    }
    tail = f" (상위 등급 보유: {upper})" if upper else ""
    return "미충족", f"{need_grade} 보유 {have}인 < 요구 {need}인{tail}"


# ── large-business-group affiliation ─────────────────────────────────────
# This is not company size. A small company can still be a group affiliate, so
# the core size field cannot stand in for this answer.
_AFFIL_REQ_RE = re.compile(r"상호출자제한|기업집단|계열\s*(?:회사|사)")
# When a size restriction sits in the same sentence, the core company-size rule
# has to weigh both together and this extension only supplies the answer.
_SIZE_IN_SAME_REQUIREMENT_RE = re.compile(
    r"(대기업|중견기업)[^.\n]{0,40}?(?:참여\s*(?:제한|불가|배제)|참가\s*불가|제외|(?:참여|참가)\s*할\s*수\s*없)"
)

_AFFIL_NO_RE = re.compile(r"아니|없|비해당|해당\s*(?:하지|되지)\s*않|미해당|무관")
_AFFIL_YES_RE = re.compile(r"해당|소속|계열|맞|그렇|네|예")


def _affiliate_detect(requirement: QualificationRequirement) -> bool:
    return bool(_AFFIL_REQ_RE.search(requirement.raw or ""))


def _affiliate_owns_judgment(requirement: QualificationRequirement) -> bool:
    # 규모 요건은 규모 규칙이 계열회사 답과 함께 판정한다. 확장이 맡으면 '대기업 및 중견기업 … 참여할 수 없으며' 의
    # 규모 배제가 사라진다(2026-10-08: 정규식이 '참여할 수 없' 을 몰라 대기업도 '아니오' 한 마디로 충족이 될 수 있었다).
    if requirement.type == "COMPANY_SIZE":
        return False
    return not _SIZE_IN_SAME_REQUIREMENT_RE.search(requirement.raw or "")


def _affiliate_parse(answer_text: str) -> dict[str, bool] | None:
    """Read yes/no in code. Ambiguous answers return None rather than a guess."""
    text = (answer_text or "").strip()
    if not text:
        return None
    # Negations are checked first: "해당 없습니다" contains both '해당' and '없'.
    if _AFFIL_NO_RE.search(text):
        return {"is_affiliate": False}
    if _AFFIL_YES_RE.search(text):
        return {"is_affiliate": True}
    return None


def _affiliate_judge(
    value: Any, requirement: QualificationRequirement
) -> tuple[str | None, str]:
    is_affiliate = value.get("is_affiliate") if isinstance(value, dict) else None
    if is_affiliate is None:
        return None, "계열회사 해당 여부를 아직 받지 못함"
    if is_affiliate:
        return "미충족", "상호출자제한기업집단 계열회사에 해당 — 공고가 참여를 제한함"
    return "충족", "상호출자제한기업집단 계열회사에 해당하지 않음"


EXTENSION_SPECS: tuple[ExtensionSpec, ...] = (
    ExtensionSpec(
        key="sw_engineer_grade",
        label="소프트웨어기술자 등급별 인원",
        domain="소프트웨어 용역",
        requirement_types=("STAFF",),
        why=(
            "공고가 소프트웨어기술자 등급(특급/고급/중급/초급)을 요구합니다. "
            "등급은 소프트웨어 용역에만 있는 개념이라 공통 프로필에는 담지 않고, "
            "이런 공고를 검토할 때만 받습니다."
        ),
        ask="보유 인력을 등급별로 알려주시겠어요? (예: 특급 2명, 고급 3명)",
        input_hint="특급 2명, 고급 3명",
        detect=_sw_grade_detect,
        parse=_sw_grade_parse,
        judge=_sw_grade_judge,
    ),
    ExtensionSpec(
        key="conglomerate_affiliate",
        label="상호출자제한기업집단 계열회사 해당 여부",
        domain="공통",
        # Any requirement type: this condition often lands outside a size slot.
        requirement_types=(),
        why=(
            "공고가 상호출자제한기업집단(대기업집단) 계열회사의 참여를 제한합니다. "
            "중소기업 이하로 확인된 회사는 법상 계열회사일 수 없어 묻지 않고, 그 밖의 회사에만 이런 공고에서 받습니다."
        ),
        ask="귀사가 상호출자제한기업집단(대기업집단) 계열회사에 해당하나요? (예 / 아니오)",
        input_hint="아니오",
        detect=_affiliate_detect,
        owns_judgment=_affiliate_owns_judgment,
        parse=_affiliate_parse,
        judge=_affiliate_judge,
    ),
)

_BY_KEY = {spec.key: spec for spec in EXTENSION_SPECS}


def get_spec(key: str) -> ExtensionSpec | None:
    return _BY_KEY.get(key)


def _matching_specs(requirement: QualificationRequirement) -> Iterator[ExtensionSpec]:
    for spec in EXTENSION_SPECS:
        if spec.requirement_types and requirement.type not in spec.requirement_types:
            continue
        if spec.detect(requirement):
            yield spec


def spec_for_requirement(
    requirement: QualificationRequirement,
) -> ExtensionSpec | None:
    """The extension that owns this requirement's judgment, if any.

    Returns None when a core rule owns the judgment even though an extension
    supplies part of the answer; `required_for()` still reports that the value
    has to be collected.
    """
    for spec in _matching_specs(requirement):
        if spec.owns_judgment and not spec.owns_judgment(requirement):
            continue
        return spec
    return None


def required_for(
    requirements: list[QualificationRequirement] | None,
) -> list[ExtensionSpec]:
    """Extensions this notice needs. Empty when the core profile is enough.

    This exists so that nothing extra is ever asked before a notice is opened.
    """
    seen: set[str] = set()
    specs: list[ExtensionSpec] = []
    for requirement in requirements or []:
        for spec in _matching_specs(requirement):
            if spec.key not in seen:
                seen.add(spec.key)
                specs.append(spec)
    return specs


def describe_required(
    requirements: list[QualificationRequirement] | None,
) -> list[dict[str, str]]:
    """`required_for()` shaped for a UI that renders the questions to ask."""
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "domain": spec.domain,
            "why": spec.why,
            "ask": spec.ask,
            "input_hint": spec.input_hint,
        }
        for spec in required_for(requirements)
    ]


def parse_answer_for(key: str, answer_text: str) -> Any:
    """Read an extension value out of a follow-up answer. None when unreadable."""
    spec = get_spec(key)
    if spec is None:
        return None
    return spec.parse(answer_text)
