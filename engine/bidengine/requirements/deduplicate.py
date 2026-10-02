"""같은 조항에서 나온 요건이 겹칠 때 정리한다.

[재현 2026-09-14] 모델의 유형 분류는 실행마다 흔들린다. 구내식당 공고(R26BK01633750)의
「나. 식품위생법에 의거 단체급식업 등록업체…영업신고(업종코드 : 1450)…」 한 조항이
실행에 따라 이렇게 나왔다.

    run0   REGISTRATION_CERTIFICATION "단체급식업등록"  +  INDUSTRY "1450"   <- 둘 다
    run1   INDUSTRY "1450"
    run2   REGISTRATION_CERTIFICATION 두 개
    이전   기타요건 (통째로 버려짐)

둘 다 나온 실행이 위험하다. 두 요건은 ALL_OF 묶음이라 **둘 다 충족해야** 하는데,
업종 1450 을 실제로 보유한 회사에 대보면

    INDUSTRY 1450                      -> SATISFIED
    REGISTRATION_CERTIFICATION 단체급식업등록 -> UNSATISFIED   <- 틀린 미달

같은 사실인데 하나는 회사의 업종 목록에서 찾고 하나는 인증 목록에서 찾는다. 자격 있는
회사가 떨어진다 — 이 기능에서 가장 나쁜 실패다.

무엇을 정리하고 무엇을 두는가
-----------------------------
겹친다고 아무거나 합치면 진짜 요건을 잃는다. 한 조항이 "전북특별자치도에 있고 업종
1257 을 등록한 업체" 처럼 서로 다른 두 요건을 정말로 담을 수도 있다. 그래서 둘만 한다.

1. **완전 중복** — 유형·값·원문이 같으면 하나만 남긴다. 잃는 것이 없다.
2. **업종 등록 ↔ 등록·인증 보유 혼동** — 프롬프트가 "혼동하지 마라" 라고 적어 둔 바로 그
   쌍이다. 짧은 원문이 긴 원문 안에 들어 있고, 긴 쪽이 업종코드를 갖고 있고, 짧은 쪽의
   값이 긴 원문 안에 글자 그대로 있을 때만 짧은 쪽을 접는다. 세 조건이 다 맞으면 같은
   사실을 두 이름으로 부른 것이다.

지역·규모·인력처럼 다른 유형끼리는 손대지 않는다. 겹쳐 보여도 정말 둘 다 필요한
요건일 수 있고, 잘못 접으면 있어야 할 판정이 사라진다.
"""

from __future__ import annotations

import re
import unicodedata

from bidengine.contracts import QualificationRequirement


_INDUSTRY_CODE_VALUE_RE = re.compile(r"^[0-9]{4}$|^[0-9]{10}$")

# 접히는 쪽의 값이 업종명 그 자체여야 한다. 한글로만 이루어지고 "…업" 으로 끝나거나
# 그 뒤에 등록·신고·허가가 붙은 모양. 숫자나 로마자가 섞이면 인증 규격 이름이다
# (ISO 9001, KS 27001). 그런 것은 별개 요건이므로 접지 않는다.
# "단체급식업등록업체", "영업신고" 처럼 등록 행위까지 붙여 쓴 값도 업종명 모양이다.
_INDUSTRY_NAME_VALUE_RE = re.compile(r"[가-힣·ㆍ]+업(?:등록|신고|허가)?(?:업체|업자)?")
# 업종 등록 행위 그 자체를 값으로 낸 것 — "인·허가", "영업신고", "등록". 인증 이름이 아니다.
# 진짜 인증은 고유명사가 붙는다(ISO 9001, 직접생산확인증명서). 이런 낱말만으로 된 값은
# 같은 조항의 업종코드가 이미 말하는 사실이다.
_REGISTRATION_ACT_VALUE_RE = re.compile(r"(?:인[·ㆍ]?허가|허가|영업신고|신고|등록)(?:필|완료)?")


# 공고문이 눈에 띄라고 찍는 기호. 공고문과 제안요청서에 같은 조항이 두 벌 있을 때 한쪽은
# ※ 로, 한쪽은 * 로 적혀 있어서 값이 한 글자 달라졌고, 그 한 글자로 완전 중복이 안 잡혔다.
# 비교할 때만 지운다 — 근거 검증(_DECORATION_MARKS_RE)과 같은 이유, 같은 목록이다.
_DECORATION_MARKS_RE = re.compile(r"[※▶▷◆◇■□●○◦☞‣✓✔★☆＊*]")


def _norm(value: object | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return re.sub(r"\s+", "", _DECORATION_MARKS_RE.sub("", text))


def _loose(value: str) -> str:
    return value.replace("·", "").replace("ㆍ", "")


def _identity(requirement: QualificationRequirement) -> tuple:
    """같은 요건인가를 정하는 열쇠. 원문은 넣지 않는다.

    [재현 2026-09-15] 같은 경험분야 요건이 원문만 다른 채 둘 나왔다 — 공고문과 제안요청서에
    같은 조항이 두 벌 있어서다. 유형·값·범위·기간이 다 같으면 어느 문서에서 읽었든 같은
    요건이다. 범위(scope)까지 넣는 이유는 금액이 같아도 경험분야가 다르면 별개 요건이기
    때문이다.
    """
    scope = requirement.scope or {}
    return (
        requirement.type,
        _norm(requirement.value),
        _norm(requirement.operator),
        _norm(requirement.period_months),
        # industry_name·kind 는 어느 슬롯에서 왔는지의 흔적이지 요건의 뜻이 아니다. 같은 코드
        # 1450 이 업종요건 슬롯과 인증요건 슬롯에서 각각 나오면 kind 만 다르고 같은 요건이다.
        # guard·guard_reason 은 가드 평가의 흔적이지 요건의 뜻이 아니다.
        # guard_basis·source_name 도 그렇다 — 가드를 무엇으로 풀었는지, 값이 어떤 이름에서 왔는지의 흔적이다.
        tuple(sorted(
            (k, _norm(v)) for k, v in scope.items()
            if k not in ("industry_name", "kind", "guard", "guard_reason", "guard_basis", "source_name")
        )),
    )


def _has_closed_identifier(requirement: QualificationRequirement) -> bool:
    return bool(_INDUSTRY_CODE_VALUE_RE.match(_norm(requirement.value)))


def _folds_into(
    candidate: QualificationRequirement,
    keeper: QualificationRequirement,
    *,
    same_clause: bool = False,
) -> bool:
    """candidate 가 keeper 와 같은 사실을 다른 이름으로 부른 것인가.

    접히는 값이 **업종명 그 자체**일 때만 인정한다. "단체급식업등록" 은 업종 1450 을
    말을 바꿔 부른 것이지만, 같은 조항에 적힌 "ISO 9001" 은 별개의 인증 요건이다.
    이 구분이 없으면 진짜 인증 요건을 삼킨다 — 실제로 첫 판에서 그랬다.
    """
    if keeper.type != "INDUSTRY" or not _has_closed_identifier(keeper):
        return False
    if candidate.type not in ("REGISTRATION_CERTIFICATION", "INDUSTRY"):
        return False
    if candidate is keeper or _has_closed_identifier(candidate):
        return False
    value = _norm(candidate.value)
    if not (
        _INDUSTRY_NAME_VALUE_RE.fullmatch(value)
        or _REGISTRATION_ACT_VALUE_RE.fullmatch(value)
    ):
        return False
    # 같은 조항인가. 둘 중 하나면 된다.
    #   (a) 한쪽 원문이 다른 쪽을 담고 있다 — 방향은 상관없다
    #   (b) 같은 청크(같은 항목)에서 나왔다 — 모델이 "나." 조항의 앞 문장과 뒷 문장을 따로
    #       인용하면 두 원문이 서로를 안 담는다. 실측(2026-09-15)에서 "단체급식업 등록업체"
    #       와 "영업신고(업종코드 : 1450)" 가 그렇게 갈렸다. 청크는 항목 단위로 잘려 있어
    #       같은 청크면 같은 조항이다.
    candidate_raw, keeper_raw = _norm(candidate.raw), _norm(keeper.raw)
    if not candidate_raw or not keeper_raw:
        return False
    contained = candidate_raw in keeper_raw or keeper_raw in candidate_raw
    if not contained and not same_clause:
        return False
    if same_clause and not contained:
        return True
    # "인허가" 와 "인·허가" 는 같은 말이다. 가운뎃점만 다른 것으로 대조가 어긋나지 않게 한다.
    loose = _loose(value)
    return loose in _loose(keeper_raw) or loose in _loose(candidate_raw)


def deduplicate_requirements(
    requirements: list[QualificationRequirement],
    *,
    source_chunk_by_key: dict[str, str | None] | None = None,
) -> tuple[list[QualificationRequirement], list[dict[str, object]]]:
    """겹친 요건을 정리하고, 접은 것은 진단으로 남긴다.

    `source_chunk_by_key` 는 requirement_key -> 그 요건이 나온 청크 id. 같은 청크에서 나온
    이름 업종과 코드 업종을 같은 조항으로 본다. 없으면 원문 포함 관계로만 판단한다.
    """
    chunk_of = source_chunk_by_key or {}

    def same_clause(a: QualificationRequirement, b: QualificationRequirement) -> bool:
        left, right = chunk_of.get(a.requirement_key), chunk_of.get(b.requirement_key)
        return bool(left) and left == right
    kept: list[QualificationRequirement] = []
    diagnostics: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()

    # 같은 대안 묶음이 두 문서(공고문 HWP 와 PDF)에 그대로 있으면 묶음째 한 번만 남긴다. 구성원 하나씩
    # 지우면 "(A 또는 B) 그리고 (A 또는 C)" 가 "(A 또는 B) 그리고 C" 로 바뀌므로(아래 주석), 구성원이
    # **전부 같은** 묶음만 통째로 접는다. 조건은 바뀌지 않는다.
    members: dict[str, list[QualificationRequirement]] = {}
    for requirement in requirements:
        if requirement.group_operator == "ANY_OF":
            members.setdefault(requirement.requirement_group_key or requirement.requirement_key, []).append(requirement)
    seen_groups: set[frozenset] = set()
    duplicate_groups: set[str] = set()
    for group_key, group in members.items():
        signature = frozenset(_identity(item) for item in group)
        if signature in seen_groups:
            duplicate_groups.add(group_key)
        seen_groups.add(signature)

    for requirement in requirements:
        if requirement.group_operator == "ANY_OF" and (
            requirement.requirement_group_key or requirement.requirement_key
        ) in duplicate_groups:
            diagnostics.append({
                "code": "DUPLICATE_REQUIREMENT",
                "raw": requirement.raw,
                "type": requirement.type,
                "value": requirement.value,
                "dropped_key": requirement.requirement_key,
            })
            continue
        # [재현 2026-09-15, 검수] identity 는 소속 그룹(requirement_group_key)을 안 본다 —
        # 두 문서에 같은 요건이 두 벌 있는 흔한 경우(그룹이 각자 하나뿐)를 잡으려면 그래야
        # 한다. 그런데 "(A 또는 B) 그리고 (A 또는 C)" 처럼 서로 다른 ANY_OF 묶음에 같은 값
        # A 가 있으면, 완전중복 규칙이 뒤에 나온 A 를 지워 조건 자체가 바뀐다 —
        # (A 또는 B) 그리고 C 가 되어 A 만 가진 회사가 미달로 뒤집힌다. ANY_OF 묶음 소속은
        # 그래서 이 정리 대상에서 아예 뺀다. 대가로 같은 대안 묶음이 두 문서에 그대로
        # 중복돼도 남지만, 그건 판정 결과를 안 바꾸는 중복일 뿐이다 — 조건이 바뀌는 쪽보다
        # 안전하다.
        if requirement.group_operator == "ANY_OF":
            kept.append(requirement)
            continue
        identity = _identity(requirement)
        if identity in seen:
            diagnostics.append({
                "code": "DUPLICATE_REQUIREMENT",
                "raw": requirement.raw,
                "type": requirement.type,
                "value": requirement.value,
                "dropped_key": requirement.requirement_key,
            })
            continue
        seen.add(identity)
        kept.append(requirement)

    folded: list[QualificationRequirement] = []
    for requirement in kept:
        keeper = next(
            (
                other
                for other in kept
                if other is not requirement
                and _folds_into(requirement, other, same_clause=same_clause(requirement, other))
            ),
            None,
        )
        if keeper is None:
            folded.append(requirement)
            continue
        diagnostics.append({
            "code": "MERGED_INDUSTRY_REGISTRATION",
            "raw": requirement.raw,
            "dropped_key": requirement.requirement_key,
            "dropped_value": requirement.value,
            "kept_key": keeper.requirement_key,
            "kept_value": keeper.value,
        })

    return folded, diagnostics
