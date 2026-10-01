"""자격 절 본문을 항목 기호로 나눠 조항 목록을 만든다.

예전 추출은 자격 절 본문을 통째로 모델에 주고, 무엇이 한 요건인지(경계)와 원문을 어디까지
인용할지(raw)를 모델이 정했다. 실측에서 같은 조항이 실행마다 다른 경계·다른 raw 로 나왔다
(docs/experiments/2026-09-30). 경계는 공고가 이미 항목 기호로 그어 두었다 — 코드가 그것을
따라 자르면 실행마다 같다.

규칙
  - 항목 기호(1. / 가. / 1) / 가) / (1) / ① / ㅇ ○ □ ■ ▶ …)로 시작하는 줄이 새 조항이다.
  - 단서 줄("※ 단, …", "- 다만 …")과 하위 항목 줄("- 소프트웨어사업(1468)")은 앞 조항에 붙는다.
    단서가 조항에 남아야 안전 가드가 보고, 우산 문장과 하위 줄은 한 조항이어야 뜻이 산다.
  - 하위 항목이 그 자체로 완결된 문장("- … 로 나라장터에 등록한 자")이면 독립 조항이다. 제목 아래에
    요건 문장을 여러 줄 늘어놓은 공고는 한 조항에 조건이 일곱 개씩 묶여 요건으로 풀리지 않았다
    (2026-10-01 표본 R26BK01744644 "가. 공통자격"). 우산 문장이 "다음 중 하나" 처럼 대안 관계를
    말하면 나누지 않는다 — 나누면 '하나만 갖추면 된다' 가 사라져 모두 필수가 된다.
  - 단서가 아닌 주석 줄("※ 자격제한 : …")은 독립 조항이다.
  - 기호 없는 줄은 앞 줄이 문장 끝으로 끝났으면 새 조항(HWP 문단), 아니면 앞 조항에 잇는다
    (PDF 줄바꿈). 항목 기호 없이 문단만으로 쓴 공고가 있다(C02 실측).
  - 조항 id 는 순서대로 C001, C002 … 이다. 같은 입력이면 같은 id 다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_ITEM_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"제\s*\d+\s*(?:조|장)"
    r"|\d+(?:\.\d+)*\s*[.)．]"
    r"|[가-힣]\s*[.)．]"
    r"|\(\s*(?:\d{1,2}|[가-힣])\s*\)"
    r"|[①-⑳]"
    r"|[ㅇ○●◦▶▷□■◆◇](?=\s)"
    r")\s*\S"
)


# 앞 조항의 단서로 붙는 줄 — "※ 단, …", "- 다만 …". 단서가 아닌 ※ 줄("※ 자격제한 : …")은
# 독립 조항이다. 붙여 버리면 그 줄의 배제 낱말이 앞 조항의 요건까지 막는다(C02 실측).
_PROVISO_RE = re.compile(r"^\s*(?:[※＊*·•\-–—☞]\s*)?(?:단\s*[,.]|단서|다만|예외|제외|또는)")
# 하위 항목 줄 — 우산 문장("다음 분야를 등록한 자") 아래의 "- 소프트웨어사업(1468)".
_CHILD_RE = re.compile(r"^\s*[\-–—·•]\s*\S")
# 문장이 끝난 줄. HWP·HWPX 는 줄이 곧 문단이지만 PDF 는 문장 중간에서도 줄을 바꾼다. 앞 줄이
# 문장 끝으로 끝났을 때만 기호 없는 줄을 새 조항으로 본다.
# "포함" 은 문장 끝이 아니다 — "… 농축공정이 포함 / 된 생산라인의 … 400,000,000원 이상인 자" 가 둘로
# 갈라져 금액이 뒤 조항에만 남았다(2026-10-01 표본 R26BK01744796).
_SENTENCE_END_RE = re.compile(r"(?:[.。]|다|(?<!포)함|음|임|것|자|업체|사업자|기업|법인)\s*[)\]]?\s*$")
# 하위 항목들 사이의 관계가 대안임을 말하는 우산 문장.
_ALTERNATIVE_UMBRELLA_RE = re.compile(r"(?:중|가운데)\s*(?:하나|어느|1\s*개|택)|어느\s*하나|택\s*1|택일|각\s*호의\s*(?:1|어느)")
_SENTENCE_CHILD_MIN_CHARS = 30


@dataclass
class Clause:
    clause_id: str
    text: str
    chunk_id: str | None = None
    source_blocks: list[dict[str, Any]] = field(default_factory=list)


def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def enumerate_clauses(chunks: list[dict[str, Any]]) -> list[Clause]:
    """선택된 자격 절 청크들을 조항 목록으로. 청크를 넘어 조항을 잇지 않는다."""
    clauses: list[Clause] = []
    for chunk in chunks:
        current: list[str] = []

        def flush() -> None:
            if current:
                clauses.append(
                    Clause(
                        clause_id=f"C{len(clauses) + 1:03d}",
                        text="\n".join(current),
                        chunk_id=chunk.get("chunk_id"),
                        source_blocks=list(chunk.get("source_blocks") or []),
                    )
                )

        lines = _lines(chunk.get("text") or "")
        split_children = True  # 지금 우산 문장 아래의 문장형 하위 항목을 나눌 것인가
        for index, line in enumerate(lines):
            is_child = bool(_CHILD_RE.match(line)) and not _PROVISO_RE.match(line)
            if current and is_child:
                if not _CHILD_RE.match(current[0]):
                    # 우산 문장 바로 아래의 첫 하위 항목에서 정한다.
                    split_children = not _ALTERNATIVE_UMBRELLA_RE.search(" ".join(current))
                starts = split_children and _is_sentence_item(lines, index)
            else:
                starts = bool(current) and _starts_new_clause(line, current[-1])
            if starts:
                flush()
                current = []
            current.append(line)
        flush()
    return clauses


def _begins_item(line: str) -> bool:
    return bool(_ITEM_MARKER_RE.match(line) or _CHILD_RE.match(line) or _PROVISO_RE.match(line)) or line.lstrip().startswith(
        ("※", "＊", "☞")
    )


def _is_sentence_item(lines: list[str], index: int) -> bool:
    """index 에서 시작하는 하위 항목(이어지는 줄 포함)이 완결된 문장인가."""
    end = index + 1
    while end < len(lines) and not _begins_item(lines[end]):
        end += 1
    text = " ".join(lines[index:end])
    return len(text) >= _SENTENCE_CHILD_MIN_CHARS and bool(_SENTENCE_END_RE.search(lines[end - 1]))


def _starts_new_clause(line: str, previous: str) -> bool:
    if _ITEM_MARKER_RE.match(line):
        return True
    if _PROVISO_RE.match(line) or _CHILD_RE.match(line):
        return False  # 단서·하위 항목은 앞 조항에 붙는다
    if line.lstrip().startswith(("※", "＊", "☞")):
        return True   # 단서가 아닌 주석 줄은 독립 조항
    return bool(_SENTENCE_END_RE.search(previous))
