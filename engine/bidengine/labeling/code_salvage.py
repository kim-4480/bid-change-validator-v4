"""모델이 빠뜨린 업종코드 조항을 코드가 원문에서 직접 채운다.

왜
--
같은 공고를 반복해 돌리면 모델이 어떤 실행에서는 업종 조항을 아예 안 올린다.
실측(2026-09-15) —

    구내식당   3회 중 1회  "영업신고(업종코드 : 1450)" 슬롯 없음
    남원글로컬 3회 중 1회  "(1257) 또는 (6770) 또는 (6786)" 조항 통째로 없음

둘 다 원문에 업종코드가 박혀 있다. 모델이 뭐라고 하든 그 숫자는 실행마다 달라지지
않는다. 그러니 모델이 빠뜨린 코드를 코드가 채운다 — 판정은 코드, 서술은 모델이라는 원칙의
추출판이다. LLM 호출은 없다.

무엇을 채우고 무엇을 안 채우나
------------------------------
선별된 청크에서 업종 맥락의 코드("업종코드 : 1450", "폐기물수집·운반업(1227)")를 찾는다.
모델 슬롯 중 어느 것도 그 코드를 담고 있지 않으면, 코드가 든 조항 줄을 그대로 raw 로 하는
업종요건 슬롯을 만든다. 원문을 그대로 쓰므로 근거 검증은 자명하게 통과한다.

안전 가드와 매핑은 그대로 거친다. "A 또는 B" 는 ANY_OF 로, 예외·부정이 붙은 조항은
UNMAPPED 로 — 코드가 채운 슬롯이라고 특별 취급하지 않는다. 채운 슬롯에는 표시를 남긴다.
모델이 왜 빠뜨렸는지는 여기서 알 수 없지만, 빠뜨렸다는 사실은 남아야 한다.
"""

from __future__ import annotations

import re
from typing import Any

# 업종 맥락의 코드만 잡는다. 네 자리 숫자 전부를 코드로 보면 연도·금액·전화번호가 걸린다.
_CODE_IN_CONTEXT_RE = re.compile(
    r"업종\s*코드\s*[:：]?\s*(?P<labelled>[0-9]{4})(?![0-9])"
    # "기타자유업(행사대행업)(9901)" — 업종명 뒤에 설명 괄호가 하나 더 끼기도 한다(J20).
    r"|[가-힣·ㆍ]{2,}업\s*\)?\s*\(\s*(?P<named>[0-9]{4})\s*\)"
)
# 항목 기호. 괄호 숫자는 (1)·(2) 처럼 한두 자리만이다 — "(6770)" 은 업종코드가 줄머리에 온
# 것이지 새 항목이 아니다. 실제 공고에서 "…폐기물중간재활용업\n(6770)또는…" 로 줄이 바뀌어
# 있었고, 네 자리를 항목으로 보면 '또는' 조항이 두 동강 나서 ANY_OF 를 못 푼다.
_ITEM_MARKER_RE = re.compile(
    r"^\s*(?:제\s*\d+\s*(?:조|장)|\d+(?:\.\d+)*\s*[.)]|[가-힣]\s*[.)]|\(\s*\d{1,2}\s*\)|[○●◦▶▷□■])\s*\S"
)
# 단서·부연 줄. 코드 조항의 raw 에는 넣지 않는다 — "※ 단, 처분 또는 재활용업 허가를…" 이
# 붙으면 '단'·'또는' 때문에 안전 가드가 막아서 정작 코드 요건이 사라진다. 판정은 "회사가
# 그 업종을 등록했는가" 이고 단서는 사람이 읽을 맥락이다. 근거(evidence)는 청크 전체를
# 가리키므로 단서는 거기에 남는다.
_CONTINUATION_RE = re.compile(r"^\s*(?:[※＊*·•\-–—]|☞)\s*\S")

# [재현 2026-09-15, 검수 3차] J14 실제 원문 — "2) …폐기물수집·운반업(1227) 등록업체" 바로
# 다음에 "※ 단, 처분 또는 재활용업 허가를 받은 업체가 관계 법령상 해당 폐기물을 직접
# 수집·운반할 수 있는 / 장비·허가 조건을 갖춘 경우에는 수집·운반업 등록을 별도로 요구하지
# 않을 수 있다"가 두 줄로 걸쳐 온다. 골든셋은 이 조항을 "1227 보유 OR 장비·허가 예외
# 확인"이라는 대안으로 본다(J13/J15 SATISFIED, J14 UNSATISFIED, J16 UNKNOWN) — 무조건
# 1227 필수가 아니다.
#
# 그런데 예전 코드는 단서 줄을 통째로 버려서 늘 "무조건 1227"로 확정했다. 반대로 예전
# 코덱스 실험처럼 단서를 모델 raw 에 그대로 남기면, 모델이 그 줄을 raw 에 담았는지 여부에
# 따라 실행마다 결과가 갈렸다(5/5 → 4/5, 검수 재현). 둘 다 아니다 — 단서가 붙었는지는
# 모델이 아니라 코드가 원문 청크에서 결정적으로 판단한다. 판정은 코드, 서술은 모델.
#
# 첫 시도에는 "갈음"만 잡아뒀는데, 실제 DB 원문은 "요구하지 않을 수 있다"로 적혀 있어서
# 안 걸렸다(라이브 재현 2026-09-15, 1227 5/5 그대로 남음). 실제 문구를 반영해 넓힌다.
_EXCEPTION_SUBSTITUTION_RE = re.compile(
    r"갈음|대체(?:할\s*수|가능)|예외|불구하고"
    r"|요구하지\s*않|필요(?:로\s*하지|하지)\s*않|생략할\s*수|면제"
)


def industry_codes_in(text: str) -> set[str]:
    # 공백·줄바꿈을 걷어내고 읽는다 — PDF 원문은 "[업⏎종코드: 5898]" 처럼 낱말 안에서도 줄을
    # 바꾼다(골든 01688607). 숫자는 사람이 달리 못 쓰는 값이라 공백을 없애도 뜻이 안 바뀐다.
    return {
        match.group("labelled") or match.group("named")
        for match in _CODE_IN_CONTEXT_RE.finditer(re.sub(r"\s+", "", text or ""))
    }


def exception_guarded_codes(chunks: list[dict[str, Any]]) -> set[str]:
    """업종코드 조항 바로 다음에 갈음·대체·예외 단서가 오면, 그 조항의 코드 집합을 낸다.

    이 집합에 든 코드는 무조건 필수로 확정하지 않는다 — 대안이 있는 조건이라 코드 하나로
    안 줄어든다. 원문 청크(모델이 뭐라고 했든 실행마다 같은 텍스트)만 보므로 결과가
    실행마다 갈리지 않는다. 좁게 둔다 — 단서가 조항 바로 다음에 올 때만 인정한다.

    [재현 2026-09-15, 라이브 검수] 실제 J14 원문의 단서는 두 줄에 걸쳐 있다 —
    "※ 단, …있는" 다음 줄에 "장비·허가 조건을 갖춘 경우에는 …요구하지 않을 수 있다"가
    이어진다. 단서 줄(※ 등) 바로 다음에 오는, 새 항목·새 단서가 아닌 줄은 그 단서
    문장이 줄바꿈으로 이어진 것으로 보고 함께 본다.
    """
    guarded: set[str] = set()
    for chunk in chunks:
        lines = [line for line in (chunk.get("text") or "").splitlines() if line.strip()]
        for index, line in enumerate(lines[:-1]):
            if _CONTINUATION_RE.match(line):
                continue
            following = lines[index + 1]
            if not _CONTINUATION_RE.match(following):
                continue
            block = [following]
            for extra in lines[index + 2:]:
                if _ITEM_MARKER_RE.match(extra) or _CONTINUATION_RE.match(extra):
                    break
                block.append(extra)
            if _EXCEPTION_SUBSTITUTION_RE.search(" ".join(block)):
                guarded |= industry_codes_in(line)
    return guarded


def _clauses(chunk_text: str) -> list[str]:
    """청크를 항목 줄로 나눈다. 줄바꿈으로 끊긴 문장은 앞 항목에 붙이고, 단서 줄은 뺀다."""
    clauses: list[str] = []
    for line in (chunk_text or "").splitlines():
        if not line.strip():
            continue
        # 단서 줄은 코드 조항에 안 붙인다 (위 주석). 단, "-[기타자유업(행사대행업)(9901)]
        # 업종을 등록한 업체" 처럼 기호로 시작해도 업종코드를 담은 줄은 단서가 아니라 항목이다
        # (J20 01684825 — 이 줄을 버려서 골든이 기대하는 9901 이 0건이었다).
        if _CONTINUATION_RE.match(line) and not industry_codes_in(line):
            continue
        if _ITEM_MARKER_RE.match(line) or not clauses:
            clauses.append(line.strip())
        else:
            clauses[-1] += "\n" + line.strip()  # 줄바꿈으로 끊긴 같은 문장
    return clauses


def salvage_missing_industry_slots(
    covered_codes: set[str],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """`covered_codes` 에 없는 업종코드를 원문 조항으로 채운 슬롯 목록을 낸다.

    덮임의 기준은 **요건으로 도달했는가**이지 모델이 냈는가가 아니다. 실측(2026-09-15)에서
    모델이 "○ … 1) A(1257) 또는 B(6770) 또는 C(6786) 등록업체 2) D(1227) 등록업체" 문단을
    통째로 한 슬롯에 담았고, 마지막 조각에 코드가 둘이라 ANY_OF 로 못 풀려 UNMAPPED 가 됐다.
    모델 슬롯의 raw 만 보고 "덮였다" 고 하면 그 네 코드는 영영 안 채워진다. 그래서
    canonical 을 거친 뒤 실제로 요건이 된 코드를 받아 나머지를 채운다.
    """
    covered = set(covered_codes)
    salvaged: list[dict[str, Any]] = []
    seen_raw: set[str] = set()
    for chunk in chunks:
        for clause in _clauses(chunk.get("text") or ""):
            codes = industry_codes_in(clause)
            missing = codes - covered
            if not missing:
                continue
            key = re.sub(r"\s+", "", clause)
            if key in seen_raw:
                continue  # 공고문·제안요청서에 같은 조항이 두 벌이면 한 번만
            seen_raw.add(key)
            salvaged.append({
                "유형": "업종요건",
                "raw": clause,
                "업종_raw": None,
                "근거조항": chunk.get("clause_label"),
                "_source_chunk_id": chunk.get("chunk_id"),
                "_source_blocks": list(chunk.get("source_blocks") or []),
                "_salvaged_codes": sorted(missing),
            })
            covered |= missing
    return salvaged
