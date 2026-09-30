"""골든셋 요건이 추출 단계를 통과해 판정기까지 도달하는지 센다.

왜 이게 따로 필요한가
--------------------
골든 러너(정답 일치 104 / 잘못된 확정 0)는 `rules.judge_requirements` 에 골든셋의
정답 요건을 **직접 넣고** 잰 것이다. 추출을 건너뛰었다. 그래서 "판정기는 오답 0" 이
맞으면서 동시에 "제품은 요건을 하나도 못 넘긴다" 가 성립할 수 있고, 실제로
R26BK01634263 에서 그랬다 — 정답 요건 3개가 원문에 다 있는데 4번 분석에서 판정기에
도달한 것이 0개였다.

이 모듈은 그 빈 구간을 잰다. 골든 요건 하나하나에 대해 제품 추출 결과 어디에
떨어졌는지를 분류한다.

    REACHED    추출돼서 판정기에 넘어감          ← 이것만 골든 러너가 본다
    DROPPED    추출됐지만 근거 검증에서 버려짐    (reason_code 와 함께)
    UNMAPPED   공고 사실로는 잡았지만 요건으로 안 봄
    MISSED     어디에도 없음

앞의 하나만 성공이고 뒤의 셋은 각각 고칠 자리가 다르다. DROPPED 는 검증기,
UNMAPPED 는 분류기, MISSED 는 추출 프롬프트·청킹이다. 한 숫자로 뭉치면 무엇을 고칠지
알 수 없다.

대조는 느슨하게, 그러나 이유가 있게
----------------------------------
모델이 인용한 문장은 원문과 특수문자·공백 수준으로 다르다("수집․운반업" 의 점).
그래서 정규화 후 부분 포함으로 맞추고, 그것도 안 되면 업종코드 같은 네 자리 숫자나
값(value)이 같으면 같은 요건으로 본다. 너무 느슨하면 아무거나 맞아서 재현율이 부풀고,
너무 엄격하면 검증기가 버린 것과 같은 이유로 놓친다. 이 기준은 테스트로 고정한다.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from dataclasses import field
from typing import Any


_DOTS = str.maketrans({"․": "·", "ㆍ": "·", "‧": "·", "・": "·", "‥": "·"})
_CODE = re.compile(r"\d{4,}")


def normalize(text: str | None) -> str:
    """비교용 정규화. 공백 제거, 호환 문자 통일, 점 종류 통일."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).translate(_DOTS)
    return re.sub(r"\s+", "", text)


def _codes(text: str | None) -> set[str]:
    return set(_CODE.findall(text or ""))


@dataclass(frozen=True)
class GoldenRequirement:
    key: str
    type: str
    raw: str
    value: Any = None


@dataclass
class Placement:
    key: str
    type: str
    outcome: str  # REACHED | DROPPED | UNMAPPED | MISSED
    reason_code: str | None = None
    matched_raw: str | None = None


@dataclass
class NoticeRecall:
    source_id: str
    placements: list[Placement] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)  # 골든셋에 없는데 추출된 것

    def count(self, outcome: str) -> int:
        return sum(1 for p in self.placements if p.outcome == outcome)


def same_requirement(golden: GoldenRequirement, candidate_raw: str | None,
                     candidate_type: str | None = None, candidate_value: Any = None) -> bool:
    """골든 요건과 추출된 후보가 같은 요건인가.

    1) 정규화한 원문이 한쪽이 다른 쪽을 포함 (짧은 쪽이 12자 이상일 때만 — "업체" 같은
       토막이 아무 데나 맞는 것을 막는다)
    2) 업종코드·품명번호 같은 네 자리 이상 숫자를 공유
    3) 유형이 같고 값이 같음 (값이 있을 때만)
    """
    g, c = normalize(golden.raw), normalize(candidate_raw)
    if g and c:
        shorter = min(len(g), len(c))
        if shorter >= 12 and (g in c or c in g):
            return True
    shared = _codes(golden.raw) & _codes(candidate_raw)
    if shared:
        return True
    if (
        golden.value is not None
        and candidate_value is not None
        and candidate_type == golden.type
        and normalize(str(golden.value)) == normalize(str(candidate_value))
    ):
        return True
    return False


def place_requirements(
    source_id: str,
    golden: list[GoldenRequirement],
    *,
    extracted: list[dict[str, Any]],
    dropped: list[dict[str, Any]],
    unmapped_raws: list[str],
) -> NoticeRecall:
    """골든 요건 각각이 제품 추출 결과 어디에 떨어졌는지 분류한다.

    `extracted` 항목은 {raw, type, value}, `dropped` 는 {raw, reason_code},
    `unmapped_raws` 는 진단에 남은 공고 사실 원문이다. 우선순위는 REACHED > DROPPED >
    UNMAPPED — 같은 요건이 여러 곳에 있으면 가장 멀리 간 것으로 센다.
    """
    recall = NoticeRecall(source_id=source_id)
    used_extracted: set[int] = set()

    for item in golden:
        placement = Placement(key=item.key, type=item.type, outcome="MISSED")
        for index, candidate in enumerate(extracted):
            if same_requirement(item, candidate.get("raw"), candidate.get("type"), candidate.get("value")):
                placement = Placement(item.key, item.type, "REACHED", matched_raw=candidate.get("raw"))
                used_extracted.add(index)
                break
        if placement.outcome == "MISSED":
            for candidate in dropped:
                if same_requirement(item, candidate.get("raw")):
                    placement = Placement(
                        item.key, item.type, "DROPPED",
                        reason_code=candidate.get("reason_code"), matched_raw=candidate.get("raw"),
                    )
                    break
        if placement.outcome == "MISSED":
            for raw in unmapped_raws:
                if same_requirement(item, raw):
                    placement = Placement(item.key, item.type, "UNMAPPED", matched_raw=raw)
                    break
        recall.placements.append(placement)

    recall.extras = [
        candidate.get("raw") or ""
        for index, candidate in enumerate(extracted)
        if index not in used_extracted
    ]
    return recall


def unmapped_raws_from_diagnostics(diagnostics: list[dict[str, Any]]) -> list[str]:
    """진단 목록에서 '공고 사실로는 봤지만 요건으로 안 본' 원문만 뽑는다."""
    raws: list[str] = []
    for item in diagnostics or []:
        if item.get("code") == "UNMAPPED_REQUIREMENT":
            raw = (item.get("details") or {}).get("raw")
            if raw:
                raws.append(raw)
    return raws
