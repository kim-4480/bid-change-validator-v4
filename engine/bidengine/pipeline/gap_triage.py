"""공백(확인 필요) 조항 가려내기.

공백은 "엔진이 담지 못한 실제 자격" 이어야 사용자가 읽을 가치가 있다. 실제로는 절 제목, 목록 머리말, 구분선,
같은 조항의 HWP·PDF 중복, PDF 줄 조각, 모든 입찰자에게 같은 결격·법령 요건, 공동수급 안내가 섞여 공고 하나에
수십 건이 나왔다(2026-10-07 표본 h: 12건에 97건, 대부분 쓸모없음). 여기서 그런 조항을 이유와 함께 '제외' 로
옮긴다. 원문은 coverage.ignored 에 남아 조항이 소리 없이 사라지지 않는다(clause_accounting).

닫힌 값(지역 이름·기업 규모 낱말·업종코드·품명번호)이 있는 조항은 제목·중복·조각 말고는 옮기지 않는다.
닫힌 값이 있는데 담지 못했다면 실제 자격을 놓쳤을 수 있어서다.
"""
from __future__ import annotations

import re
from typing import Iterable

_PREDICATE_RE = re.compile(r"(?:이어야|하여야|해야|니다|한다|한함|않음|없음|있음|불가|가능|허용|금지|함|음|됨|임|자|업체|것)\s*[.。]?\s*$")
_LIST_INTRO_RE = re.compile(
    r"(?:다음|아래|하기)\s*(?:의|각)?\s*.{0,25}?(?:각\s*호|어느\s*하나|모두|요건|자격)"
)
_JOINT_RE = re.compile(r"공동\s*(?:수급|계약|도급|이행)|분담\s*이행|하도급")
# 건설업역 상호시장 진출(종합↔전문) 허용·불허 안내. 자격을 좁히지 않는다 — 참고 정보로 보여 준다.
_MUTUAL_MARKET_RE = re.compile(r"상호\s*시장\s*진출")
# 수의계약 배제 사유·청렴 서약처럼 모든 입찰자에게 같은 결격. 회사 프로필로 판정할 자격이 아니다.
_COMMON_EXTRA_RE = re.compile(
    r"수의\s*계약\s*배제|지방\s*의회\s*의원|지방자치단체의\s*장|계약\s*이행\s*능력이\s*없|지연\s*배상금|청렴|"
    r"법(?:\s*률)?\s*제\s*3\s*3\s*조|수의\s*계약\s*운영\s*요령|제\s*8\s*조\s*의\s*2|입찰\s*참가\s*(?:자격\s*)?제한\s*(?:대상|을\s*받|받|기간)|"
    r"부실\s*이행|정당한\s*(?:이유|사유)\s*없이|특별\s*재난\s*지역|등록\s*기준에\s*미달|자격\s*요건\s*등을\s*충족하지\s*아니한"
)
# 제재 조항의 지역 이름은 발주처다("부산광역시에서 발주하는 입찰에 참가하지 못한다") — 지역 자격이 아니다.
_SANCTION_RE = re.compile(r"부정당|담합|뇌물|금품|향응|참가\s*자격\s*제한\s*처분")
_SEPARATOR_RE = re.compile(r"[-=_─━~*]{3,}")
# 앞 조항에서 잘려 나온 꼬리("이어야 합니다 .", "로 입찰참가자격 제한을 받지 않은 자")
_TAIL_RE = re.compile(r"^(?:이어야|하여야|해야|합니다|한다)")
# 국가·지방계약법 시행령 제12·13조, 시행규칙 제14조의 기본 자격 — 모든 입찰자의 공통 요건.
_STATUTE_BASELINE_RE = re.compile(
    r"(?:(?:시행령|시행규칙|법률|계약법).{0,40}?|^)제\s*1\s*[234]\s*조"
    # 발주 기관 내부 규정의 참가 자격 조문("우리 의학원 계약업무요령 제16조(참가자격)…의 규정에 의한 자격요건")
    r"|(?:계약\s*업무\s*요령|계약\s*사무\s*(?:처리\s*)?(?:규정|규칙)|회계\s*규정).{0,40}?제\s*\d+\s*조"
)
# 법령 이름·조문 번호를 걷어내면 남는 것이 없는 조각("다. 「…법률」 제31조의5 및 같은 법 시행령").
_STATUTE_TOKENS_RE = re.compile(
    r"[「『][^」』]*[」』]|제\s*\d*\s*조(?:\s*의\s*\d+)?|제\s*\d*\s*항|제\s*\d*\s*호|같은\s*법|동\s*법|시행령|시행규칙|법률|"
    r"및|또는|에\s*따른|에\s*의한|에\s*따라|의|에|규정|^[가-하]\s*\.|^[①-⑳]|^\d+\s*[.)]"
)
_SUBSTANTIVE_RE = re.compile(r"면허|[가-힣]업\s*(?:을|으로|를|에)?\s*등록|인증|허가|실적|기술자|기술인|보유|소재|업종|품명|확인서|증명서|증명원|확약서|시설|장비")
_PROCEDURE_RE = re.compile(
    r"입찰\s*보증금|서약서|예정\s*가격|낙찰자\s*결정|입찰\s*무효|무효\s*로\s*(?:합니다|함|처리)|안전\s*및\s*보건|유의\s*사항|이용자\s*등록|"
    r"인감|변경\s*등록|"
    r"입찰\s*참가\s*(?:자격\s*)?등록\s*(?:규정|마감|을\s*하|한\s*자|된\s*업체)"
)
_REGION_RESTATE_RE = re.compile(r"(?:이외|그\s*외|타)\s*지역")
# 코드가 구조를 보고 일부러 남긴 공백 — 대안·예외, 조항을 건넌 대안, 극성 이견, 규모 합집합, 지역 좁힘, 값 매핑 실패.
# 낱말 규칙으로 지우지 않는다(중복·조각만 합친다).
_STRUCTURAL_REASONS = {"ALTERNATIVE_OR_EXCEPTION_RULE", "CROSS_CLAUSE_ALTERNATIVE", "POLARITY_DISAGREEMENT",
                       "SIZE_UNION_UNKNOWN", "REGION_NARROWED"}


def _compact(text: str) -> str:
    return "".join((text or "").split())


def _hangul(text: str) -> int:
    return len(re.findall(r"[가-힣]", text or ""))


def classify_gap(raw: str, *, seen: set[str] = frozenset(), containers: Iterable[str] = (),
                 has_region_requirement: bool = False, reason: str | None = None) -> str | None:
    """공백 조항이 쓸모없는 이유. 실제 자격일 수 있으면 None.

    seen: 앞서 남긴 공백 원문(띄어쓰기를 지운 것). containers: 요건이 된 조항과 다른 공백의 원문(띄어쓰기를 지운 것)
    — 이 안에 통째로 들어가는 더 짧은 조항은 PDF 줄 조각이다.
    """
    from bidengine.requirements.legacy_slots import has_closed_value_text, is_common_disqualification

    text = " ".join(_SEPARATOR_RE.sub(" ", raw or "").split())
    compact = _compact(text)
    if _hangul(text) < 4:
        return "NO_CONTENT"
    if compact in seen:
        return "DUPLICATE"
    if len(compact) >= 8 and any(compact in other and len(other) > len(compact) for other in containers):
        return "FRAGMENT_OF_CLAUSE"
    # PDF 는 글자마다 띄어 쓴 줄이 많다("입 찰 참 가 자 격") — 낱말 규칙은 띄어쓰기를 지운 문장에도 대 본다.
    def has(pattern: re.Pattern[str]) -> bool:
        return bool(pattern.search(text) or pattern.search(compact))

    if reason in _STRUCTURAL_REASONS or (reason or "").startswith("UNMAPPED_"):
        return None
    substantive = has(_SUBSTANTIVE_RE)
    if len(compact) <= 12 and _TAIL_RE.search(compact) and not substantive:
        return "FRAGMENT_OF_CLAUSE"
    closed = has_closed_value_text(text)
    if closed and has(_SANCTION_RE) and not has_closed_value_text(_REGION_FREE(text)):
        closed = False
    if closed:
        return None
    if has(_JOINT_RE):
        # 공동수급·하도급 허용 여부는 회사 자격이 아니라 입찰 방식이다 — 확인 목록이 아니라 참고 정보로 보여 준다.
        return "JOINT_CONTRACT_NOTE"
    if has(_MUTUAL_MARKET_RE):
        return "MUTUAL_MARKET_NOTE"
    if len(compact) <= 30 and not _PREDICATE_RE.search(compact) and not substantive:
        return "HEADING"
    if len(compact) <= 70 and has(_LIST_INTRO_RE) and not substantive:
        return "LIST_INTRO"
    if _hangul(_STATUTE_TOKENS_RE.sub(" ", text)) <= 4 and _STATUTE_TOKENS_RE.search(text):
        return "STATUTE_FRAGMENT"
    if is_common_disqualification(text) or is_common_disqualification(compact) or has(_COMMON_EXTRA_RE) or has(_SANCTION_RE):
        return "COMMON_DISQUALIFICATION"
    if has(_STATUTE_BASELINE_RE) and not substantive:
        return "STATUTE_BASELINE"
    if has(_PROCEDURE_RE) and not substantive:
        return "PROCEDURE"
    if has_region_requirement and has(_REGION_RESTATE_RE):
        return "REGION_RESTATED"
    return None


def _REGION_FREE(text: str) -> str:
    """지역 이름을 지운 문장 — 지역 말고 다른 닫힌 값(규모·코드)이 남는지 보려고 쓴다."""
    from bidengine.normalization.regions import region_tokens

    for token in sorted(set(region_tokens(text)), key=len, reverse=True):
        text = text.replace(token, " ")
    return text


def triage_gaps(gaps: list, requirements: list) -> tuple[list, list]:
    """UNREPRESENTABLE·UNCLASSIFIED 공백 중 쓸모없는 것을 (남길 공백, 제외로 옮길 (공백, 이유)) 로 나눈다."""
    requirement_raws = [_compact(r.raw) for r in requirements if r.raw]
    gap_raws = [_compact(g.raw) for g in gaps if g.raw]
    has_region = any(r.type == "REGION" for r in requirements)
    kept, moved, seen = [], [], set()
    for gap in gaps:
        if gap.kind == "DROPPED":
            # 검증에서 탈락한 조항은 실제 자격이라 남긴다. HWP·PDF 에 같은 조항이 두 번 나온 것만 합친다.
            if gap.raw and _compact(gap.raw) in seen:
                moved.append((gap, "DUPLICATE"))
            else:
                kept.append(gap)
                seen.add(_compact(gap.raw))
            continue
        if gap.kind not in {"UNREPRESENTABLE", "UNCLASSIFIED"}:
            kept.append(gap)
            continue
        reason = classify_gap(gap.raw, seen=seen, containers=[*requirement_raws, *gap_raws], has_region_requirement=has_region,
                              reason=gap.reason)
        if reason:
            moved.append((gap, reason))
        else:
            kept.append(gap)
            seen.add(_compact(gap.raw))
    return kept, moved


def closed_values_in(text: str) -> dict[str, set[str]]:
    """조항에 적힌 닫힌 값: 업종코드·품명번호, 지역 이름, 규모 낱말."""
    from bidengine.judgment.clause_safety import strip_decorations
    from bidengine.normalization.regions import find_regions
    from bidengine.requirements.legacy_slots import (
        _INDUSTRY_CODE_RE, _NAMED_INDUSTRY_CODE_RE, _PAREN_CODE_RE, _PRODUCT_CODE_RE, _SIZE_WORD_RE, _size_text,
    )

    compact = _compact(text)
    codes = {code for group in _INDUSTRY_CODE_RE.findall(compact) for code in re.findall(r"[0-9]{4}", group)}
    codes |= set(_NAMED_INDUSTRY_CODE_RE.findall(compact)) | set(_PAREN_CODE_RE.findall(compact)) | set(_PRODUCT_CODE_RE.findall(compact))
    sidos, subs = find_regions(strip_decorations(text or ""))
    return {"codes": codes, "regions": set(sidos) | set(subs), "sizes": set(_SIZE_WORD_RE.findall(_size_text(text or "")))}


# (가)·(나) 가 남긴 공백 — 담긴 값과 상관없이 업종을 놓쳤거나 대안이 빠졌다는 뜻이라 항상 판정을 막는다.
_ALWAYS_BLOCKING = ("ALTERNATIVE_UNRESOLVED", "INDUSTRY_NAME_UNRESOLVED", "CANDIDATE_UNUSED")


def closed_values_covered(gap, requirements: list) -> bool:
    """공백 조항의 닫힌 값이 모두 이미 요건으로 담겼는가. 그러면 그 조항의 나머지는 확인 항목이다.

    "관광호텔업(업종코드1264) 분야의 등록을 필한 5성급 호텔" — 1264 는 요건으로 담겼고 남은 '5성급' 은 사용자가 확인한다.
    """
    if any(tag in (gap.reason or "") for tag in _ALWAYS_BLOCKING):
        return False
    found = closed_values_in(gap.raw)
    if not any(found.values()):
        return False
    values = {str(r.value) for r in requirements}
    values |= {str(code) for r in requirements for code in ((getattr(r, "scope", None) or {}).get("with_codes") or [])}
    regions = [str(r.value) for r in requirements if r.type == "REGION"]
    if not found["codes"] <= values:
        return False
    if any(not any(region in value or value.split()[-1] in region for value in regions) for region in found["regions"]):
        return False
    return not (found["sizes"] and not any(r.type == "COMPANY_SIZE" for r in requirements))
