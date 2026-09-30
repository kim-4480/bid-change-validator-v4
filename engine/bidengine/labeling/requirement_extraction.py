"""Eligibility requirement extraction over semantic chunks.

The production boundary is:

    backend extracted_blocks
        -> canonical source blocks
        -> semantic chunks
        -> structured extractor (LLM adapter supplied by caller)
        -> validated extraction slots

The LLM extracts source text only. Deterministic code validates, normalizes,
resolves canonical values, and later judges them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from typing import Any

StructuredExtractor = Callable[[str, str, dict[str, Any]], dict[str, Any]]

_SECTION_HEADER_KEYWORDS = (
    "참가자격",
    "입찰참가",
    "자격요건",
    "참가 자격",
    "신청자격",
    "제한사항",
)

_FALLBACK_REQUIREMENT_KEYWORDS = (
    *_SECTION_HEADER_KEYWORDS,
    "실적",
    "면허",
    "인증",
    "등록",
    "소재",
    "지역",
    "인력",
    "업종",
    "업태",
    "경험",
    "분야",
    "소상공인",
    "소기업",
    "중소기업",
    "중견기업",
    "대기업",
)

_DETAIL_RAW_FIELDS = (
    "기간_raw",
    "금액_raw",
    "건수_raw",
    "업종_raw",
    "경험분야_raw",
    "지역_raw",
    "인원_raw",
    "인력역할_raw",
    "등록인증_raw",
    "발급기관_raw",
    "기업규모_raw",
    "실적기관_raw",
)


def _nullable_source_string(description: str) -> dict[str, Any]:
    return {"type": ["string", "null"], "description": description}


SLOT_SCHEMA: dict[str, Any] = {
    "name": "eligibility_slots",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "유형": {
                            "type": "string",
                            "enum": [
                                "실적요건",
                                "인력요건",
                                "인증요건",
                                "면허요건",
                                "등록요건",
                                "지역요건",
                                "업종요건",
                                "경험분야요건",
                                "기업규모요건",
                                "기타요건",
                            ],
                        },
                        "raw": {"type": "string", "description": "요건 원문 그대로. 요약·변형 금지"},
                        "기간_raw": _nullable_source_string("기간 표현 원문. 없으면 null"),
                        "금액_raw": _nullable_source_string("금액 표현 원문. 없으면 null"),
                        "건수_raw": _nullable_source_string("실적 건수 표현 원문. 없으면 null"),
                        "업종_raw": _nullable_source_string("업종·업태 제한 원문 명칭. 없으면 null"),
                        "경험분야_raw": _nullable_source_string("과거 실적/경험에서 요구하는 분야 원문. 없으면 null"),
                        "지역_raw": _nullable_source_string("지역·소재지 제한의 원문 명칭. 없으면 null"),
                        "인원_raw": _nullable_source_string("필요 인원 수 표현 원문. 없으면 null"),
                        "인력역할_raw": _nullable_source_string("요구 인력 역할·자격·등급 원문. 없으면 null"),
                        "등록인증_raw": _nullable_source_string("등록·면허·인증 명칭 원문. 없으면 null"),
                        "발급기관_raw": _nullable_source_string("등록·면허·인증 발급기관 원문. 없으면 null"),
                        "기업규모_raw": _nullable_source_string("소상공인·소기업·중소기업·중견기업 등 기업규모 원문. 없으면 null"),
                        "실적기관_raw": _nullable_source_string("실적 대상 발주기관·고객 범위 원문. 없으면 null"),
                        "근거조항": _nullable_source_string("이 요건이 적힌 문서 자체의 조항 번호/라벨(예: 2, 3.1, 제5조). 인용된 법령 조문은 제외. 없으면 null"),
                    },
                    "required": ["유형", "raw", *_DETAIL_RAW_FIELDS, "근거조항"],
                },
            }
        },
        "required": ["requirements"],
    },
}

SYSTEM_PROMPT = """너는 입찰공고 RFP에서 참가자격 요건을 추출하는 도구다. 규칙:
1. 본문에 명시된 요건만 추출한다. 없는 요건을 만들어내지 마라. 없으면 빈 배열.
2. raw에는 원문 문장을 그대로 담는다. 요약하거나 수치·코드·enum으로 변환하지 마라.
3. 모든 *_raw 필드는 원문에서 **연속된 한 구간을 그대로 복사**한다. 요약·축약·조사 수정 금지. ※ ○ ▶ 같은 기호도 원문에 있으면 함께 복사한다. 해당 표현이 없으면 null로 둔다. 여러 조건을 쉼표·세미콜론으로 이어 붙이지 마라 — 조건이 여럿이면 각각 별도 requirement로 낸다. 복사한 구간이 원문과 한 글자라도 다르면 그 값은 버려진다.
4. 실적요건은 기간/금액/건수/경험분야/실적기관 표현을 같은 슬롯에 함께 담을 수 있다.
5. 업종·업태 자체가 참가 제한이면 유형=업종요건, 업종_raw에 원문 명칭을 담는다. 등록·면허·인증 보유 여부와 혼동하지 마라.
6. 금액·건수와 독립적으로 특정 경험 분야 보유 자체를 요구하는 경우에만 유형=경험분야요건을 사용한다.
7. 인력요건은 인원_raw와 인력역할_raw를 가능한 범위에서 분리한다.
8. 인증·면허·등록 요건은 '특정 등록/면허/인증을 보유 또는 완료해야 한다'는 단일 사실일 때만 각각 인증요건/면허요건/등록요건으로 분류한다. 등록인증_raw에는 실제 명칭을 담는다.
9. 소재지 제한은 유형=지역요건, 지역_raw에 원문 지역명을 담는다.
10. 소상공인·소기업·중소기업·중견기업·대기업 등 규모 제한은 유형=기업규모요건, 기업규모_raw에 원문 표현을 담는다. Backend enum으로 변환하지 마라.
11. 근거조항에는 이 요건이 적힌 문서 자체의 조항 번호(예: 2, 3.1, 제5조)만 적는다. 요건 문장이 인용하는 법령 조문은 문서 위치가 아니다. 문서 조항 번호를 알 수 없으면 null로 둔다.
12. 공동수급/공동계약 구성원·대표사 관계, 대표자 중복, 변경등록, 입찰무효, 법령상 예외, '아니어야 한다/하지 않아야 한다' 같은 부정 조건, 여러 조건이 '또는/다만/각 호'로 결합된 복합 절차 조건은 단순 등록·면허·인증 보유 요건으로 축약하지 마라. 닫힌 canonical 유형 하나로 안전하게 표현할 수 없으면 유형=기타요건으로 둔다.
13. 원문에 여러 독립적인 원자 조건이 명시되어 있으면 한 문장을 임의 요약하지 말고 각각 별도 requirement로 추출한다. 단, 논리 관계를 잃게 되는 복합조건은 억지로 분해하지 말고 기타요건으로 둔다.
14. 참가자격 섹션뿐 아니라 첨부 제안요청서·과업지시서에서 명시적으로 참가 자격을 요구하는 실적/인력/업종/지역/기업규모 조건도 추출 대상이다."""

_TOP_LEVEL_LABEL_RE = re.compile(r"^(?:\d+|[가-힣]|[IVXivx]+|제\d+조(?:의\d+)?|제\d+장)$")

# 한국 공고의 항목 위계. 숫자 1. 아래에 가. 아래에 1) 아래에 가) 가 온다.
# 예전에는 이 넷을 전부 "상위 제목"으로 봐서, "3. 입찰참가자격" 의 자식을 걷다가
# 바로 다음 "가." 에서 멈췄다. 자격 절의 본문(가·나·다 …)이 통째로 빠졌고, 그 항목들은
# 제목에 키워드가 없어 앵커도 못 됐다. 위계를 분리해 자식 항목은 다음 동급·상위
# 제목이 나타날 때까지 자격 절과 함께 전달한다.
_LABEL_RANK_PATTERNS = (
    (re.compile(r"^(?:제\d+장|제\d+조(?:의\d+)?)$"), 0),   # 제N장 · 제N조
    (re.compile(r"^(?:\d+|[IVXivx]+)$"), 10),               # 1.  Ⅰ.
    (re.compile(r"^[가-힣]$"), 20),                          # 가.
    (re.compile(r"^\d+\)$"), 30),                           # 1)
    (re.compile(r"^[가-힣]\)$"), 40),                        # 가)
    (re.compile(r"^\(\d+\)$"), 50),                         # (1)
)


# 청커는 라벨에서 괄호를 뗀다 — "1)" 도 "1." 도 clause_label 은 '1' 이다. 위계는
# 본문 첫 줄에 남아 있는 실제 기호로 읽는다.
_HEADING_MARKER_RE = re.compile(
    r"^\s*(?:(?P<paren_num>\(\d+\))|(?P<num_paren>\d+\))|(?P<han_paren>[가-힣]\))"
    r"|(?P<dotted>\d+(?:\.\d+)+)|(?P<num>\d+)\s*[.．]|(?P<han>[가-힣])\s*[.．]"
    r"|(?P<article>제\d+(?:장|조(?:의\d+)?)))"
)
_MARKER_RANK = {
    "article": 0,
    "num": 10,
    "han": 20,
    "num_paren": 30,
    "han_paren": 40,
    "paren_num": 50,
}


def _label_rank(chunk: dict[str, Any]) -> int | None:
    """항목 기호의 위계. 낮을수록 상위. 기호가 없으면 None."""
    label = str(chunk.get("clause_label") or "").strip()
    if not label:
        return None
    marker = _HEADING_MARKER_RE.match(_heading_text(chunk))
    if marker:
        if marker.lastgroup == "dotted":
            # 숫자 절 안에서 점 하나마다 한 단계 깊어진다. 한글 항목(가.)보다
            # 앞선 대역을 써서 `3.1 참가자격 -> 가. 업종`도 자식으로 유지한다.
            return 10 + marker.group("dotted").count(".")
        return _MARKER_RANK[marker.lastgroup]
    for pattern, rank in _LABEL_RANK_PATTERNS:
        if pattern.match(label):
            return rank
    return None


def _is_top_level(chunk: dict[str, Any]) -> bool:
    label = chunk.get("clause_label")
    return bool(label) and bool(_TOP_LEVEL_LABEL_RE.match(str(label).strip()))


def _chunk_document_id(chunk: dict[str, Any]) -> str | None:
    document_ids = {str(block.get("document_id")) for block in list(chunk.get("source_blocks") or []) if block.get("document_id")}
    return next(iter(document_ids)) if len(document_ids) == 1 else None


def _heading_text(chunk: dict[str, Any]) -> str:
    text = (chunk.get("text") or "").strip()
    return text.splitlines()[0] if text else ""


def _is_eligibility_section_anchor(chunk: dict[str, Any]) -> bool:
    rank = _label_rank(chunk)
    if rank is None:
        return False
    heading = _heading_text(chunk)
    return any(keyword in heading for keyword in _SECTION_HEADER_KEYWORDS)


def select_eligibility_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select eligibility sections and their children without crossing documents."""
    selected: dict[int, dict[str, Any]] = {}
    anchors = [index for index, chunk in enumerate(chunks) if _is_eligibility_section_anchor(chunk)]

    for index in anchors:
        anchor = chunks[index]
        selected[index] = anchor
        anchor_document_id = _chunk_document_id(anchor)
        anchor_rank = _label_rank(anchor)
        for child_index in range(index + 1, len(chunks)):
            candidate = chunks[child_index]
            candidate_document_id = _chunk_document_id(candidate)
            if anchor_document_id is not None and candidate_document_id is not None and candidate_document_id != anchor_document_id:
                break
            # 앵커와 같거나 더 상위인 기호가 나오면 절이 끝난 것이다. 더 깊은 기호
            # (3. 아래의 가., 가. 아래의 1))는 그 절의 본문이므로 계속 걷는다.
            candidate_rank = _label_rank(candidate)
            if candidate_rank is not None and (anchor_rank is None or candidate_rank <= anchor_rank):
                break
            selected[child_index] = candidate

    anchored_documents = {_chunk_document_id(chunks[index]) for index in anchors}
    fallback_keywords = _FALLBACK_REQUIREMENT_KEYWORDS[len(_SECTION_HEADER_KEYWORDS):] if anchors else _FALLBACK_REQUIREMENT_KEYWORDS
    for index, chunk in enumerate(chunks):
        if _chunk_document_id(chunk) not in anchored_documents and any(keyword in (chunk.get("text") or "") for keyword in fallback_keywords):
            selected[index] = chunk
    return [selected[index] for index in sorted(selected)] if selected else chunks


_GROUNDING_PUNCTUATION = str.maketrans(
    {
        "․": "·",
        "ㆍ": "·",
        "‧": "·",
        "・": "·",
        "‥": "·",
        "（": "(",
        "）": ")",
    }
)


# 공고문이 눈에 띄라고 찍는 기호들. 모델은 인용할 때 이것을 빼고 적는 일이 잦다 —
# 원문 "각 단체급식소※(1일 평균 800식 이상)" 에 대해 모델은 "각 단체급식소(1일 평균
# 800식 이상)" 라고 쓴다. 같은 문장인데 대조가 어긋나 DETAIL_NOT_FOUND_IN_SOURCE 가 났다.
# 비교할 때만 지운다. 저장되는 raw 는 그대로다.
_DECORATION_MARKS_RE = re.compile(r"[※▶▷◆◇■□●○◦☞‣✓✔★☆]")

# [재현 2026-09-15, 우치공원 1/5 PARTIAL] PDF 는 쪽 번호를 "- 4 -" 한 줄로 찍는다. 청크 안에서
# 그 줄이 문장 한가운데 오면(쪽이 바뀌는 자리) 대조용 본문이 "종사자의-4-안전" 이 되고, 모델은
# 당연히 그 마커 없이 인용하니 RAW_NOT_FOUND_IN_SOURCE 로 버려져 분석이 PARTIAL 로 떨어졌다.
# 쪽 번호는 공고의 말이 아니다 — 대조에서도, 저장되는 값에서도 걷어낸다. 한 줄 전체가 마커일
# 때만 잡는다(날짜 "2026-09-15" 같은 하이픈 숫자는 줄 전체가 아니라 안 걸린다).
_PAGE_MARKER_RE = re.compile(r"(?m)^[ \t]*-\s*\d{1,3}\s*-[ \t]*$")


def _page_marker_indices(value: str) -> set[int]:
    skip: set[int] = set()
    for match in _PAGE_MARKER_RE.finditer(value):
        skip.update(range(match.start(), match.end()))
    return skip


def _squash(value: str) -> str:
    """Normalize source text only for containment checks; stored raw stays untouched."""
    # U+2024 (ONE DOT LEADER) becomes an ASCII period under NFKC, so translate
    # punctuation variants first and apply compatibility normalization afterward.
    normalized = unicodedata.normalize("NFKC", _PAGE_MARKER_RE.sub("", value).translate(_GROUNDING_PUNCTUATION))
    normalized = _DECORATION_MARKS_RE.sub("", normalized)
    return re.sub(r"\s+", "", normalized)


def _squash_with_map(value: str) -> tuple[str, list[int]]:
    """`_squash` 와 같은 결과에, 글자마다 원문 어디서 왔는지를 함께 낸다.

    글자 단위로 돌리는 이유는 NFKC 가 길이를 바꾸기 때문이다(㈜ -> (주)). 통째로
    정규화한 뒤 위치를 세면 어긋난다.
    """
    squashed: list[str] = []
    origin: list[int] = []
    skip = _page_marker_indices(value)
    for index, char in enumerate(value):
        if index in skip:
            continue
        piece = unicodedata.normalize("NFKC", char.translate(_GROUNDING_PUNCTUATION))
        piece = _DECORATION_MARKS_RE.sub("", piece)
        piece = re.sub(r"\s+", "", piece)
        for produced in piece:
            squashed.append(produced)
            origin.append(index)
    return "".join(squashed), origin


def join_wrapped_lines(text: str) -> str:
    """저장되는 값에서 PDF 줄바꿈·쪽 번호를 걷어낸다.

    [재현 2026-09-15] REGION 값이 "전북특⏎별자치도" 로, raw 가 "…재활용업⏎(6770)또는…" 로
    저장됐다. 판정은 공백을 접어 비교하니 통과했지만 화면엔 그대로 보이고, 같은 조항의 raw 가
    실행마다 줄바꿈 위치만 달라 지문이 갈렸다(코덱스 Core-4 실행 기록). 한국어 PDF 의 줄바꿈은
    낱말 한가운데서도 일어나므로 공백 없이 잇는다 — 원래 띄어쓰기는 줄바꿈 앞에 공백 문자로
    남아 있다. 대조(_squash)가 이미 같은 가정을 쓴다.
    """
    text = _PAGE_MARKER_RE.sub("", text or "")
    text = re.sub(r"[ \t]*\r?\n[ \t]*", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


# 모델이 같은 문장에서 어디까지 끊어 적을지가 실행마다 다르다. 실측(2026-09-14) —
#
#   run0  "각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영"
#   run1  "단체급식소"                                   <- 판정에 쓸 수 없을 만큼 짧다
#   run2  "각 단체급식소※(1일 평균 800식 이상)를 1년 이상 운영한 실적"
#
# 원문 구간으로 스냅해도 이건 안 잡힌다. 스냅은 "원문과 다른 글자" 를 없앨 뿐
# "어디부터 어디까지" 를 정하지 않는다. 그래서 구간을 **문장 경계까지 넓힌다** —
# 셋 다 같은 문장 안이므로 같은 값이 된다.
#
# 넓히는 필드를 경험분야 하나로 둔다. 지역·업종·인증처럼 값 자체를 회사 프로필과
# 맞대는 필드를 문장으로 넓히면 비교가 깨진다.
_SENTENCE_LEVEL_FIELDS = ("경험분야_raw",)
_SENTENCE_BOUNDARY_RE = re.compile(r"(?:(?<=다[.])|(?<=[.!?。]))\s|\n")


def _sentence_span(source: str, start: int, end: int) -> tuple[int, int]:
    """[start, end) 를 감싸는 문장의 경계."""
    left = 0
    right = len(source)
    for match in _SENTENCE_BOUNDARY_RE.finditer(source):
        if match.end() <= start:
            left = match.end()
        elif match.start() >= end:
            right = match.start()
            break
    return left, right


def snap_to_source_span(detail: str, source: str, *, whole_sentence: bool = False) -> str | None:
    """모델이 적은 세부값을 **원문의 실제 구간**으로 바꿔 준다. 없으면 None.

    모델은 원문을 그대로 옮기라고 해도 옮기지 않는다. ※ 를 빼고, 값 둘을 쉼표로 잇고,
    조사를 다듬는다. 그 결과가 실행마다 다르고, 판정과 차수 비교가 그 글자를 본다.

    그래서 모델 값은 **가리키는 손가락**으로만 쓰고, 저장되는 값은 원문에서 잘라 온다.
    같은 구간을 가리키면 모델이 뭐라고 적었든 같은 글자가 저장된다.
    """
    squashed_source, origin = _squash_with_map(source)
    squashed_detail = _squash(detail)
    if not squashed_detail or not squashed_source:
        return None
    position = squashed_source.find(squashed_detail)
    if position < 0:
        return None
    start = origin[position]
    end = origin[position + len(squashed_detail) - 1] + 1
    if whole_sentence:
        start, end = _sentence_span(source, start, end)
    return join_wrapped_lines(source[start:end])


def _normalize_reference(value: str) -> str:
    return re.sub(r"^(?:조항|제)\s*", "", value.strip()).rstrip(".)조항 ")


_REFERENCE_SPLIT_RE = re.compile(r"[,、·]|\s+및\s+|\s+과\s+|\s+와\s+")


def _reference_parts(reference: str) -> list[str]:
    return [part.strip() for part in _REFERENCE_SPLIT_RE.split(reference) if part.strip()]


def classify_clause_reference(
    reference: str,
    chunks: list[dict[str, Any]],
    source_chunk: dict[str, Any] | None,
) -> str:
    """Classify a model-supplied reference without discarding grounded text."""
    parts = _reference_parts(reference)
    if not parts:
        return "UNVERIFIED"

    source_labels: set[str] = set()
    if source_chunk and source_chunk.get("clause_label"):
        source_labels.add(str(source_chunk["clause_label"]))
    source_text = (source_chunk.get("text") or "") if source_chunk else ""
    if source_labels and all(
        part in source_labels or _normalize_reference(part) in source_labels
        for part in parts
    ):
        return "DOCUMENT_CLAUSE"
    if source_text and all(
        re.search(
            r"(?m)^\s*" + re.escape(_normalize_reference(part)) + r"(?:[.)\s]|$)",
            source_text,
        )
        for part in parts
    ):
        return "DOCUMENT_CLAUSE"

    haystack = _squash(source_text)
    if not haystack:
        haystack = "".join(_squash(chunk.get("text") or "") for chunk in chunks)
    if haystack and all(_squash(part) in haystack for part in parts):
        return "STATUTE"
    return "UNVERIFIED"


def _find_source_chunk(raw: str, chunks: list[dict[str, Any]]) -> dict[str, Any] | None:
    probe = _squash(raw)
    if not probe:
        return None
    for chunk in chunks:
        if probe in _squash(chunk.get("text") or ""):
            return chunk
    return None


# 한 필드에 조건이 둘 이상이면 모델은 세미콜론이나 쉼표로 잇는다. 실측(2026-09-14) 값 —
#
#   기간_raw     "입찰 공고일 기준 2년 내에; 1년 이상"
#   등록인증_raw "식품위생법에 따른 인·허가, 영업신고(업종코드:1450)"
#
# 조각은 전부 원문에 있는데 **이어붙인 문자열**이 원문에 없다. 그것을 통째로 찾다가
# DETAIL_NOT_FOUND_IN_SOURCE 로 버렸다 — 지어낸 값이 아니라 우리 대조가 못 따라간 것이다.
#
# 통째로 먼저 찾고, 없을 때만 쪼갠다. 쉼표는 값 안에도 나오므로("대표자 전원의 성명을
# 모두 등재, 각자대표도 해당") 쪼개는 것이 항상 옳지는 않다. 그래도 안전한 이유는
# **조각 하나라도 원문에 없으면 그대로 버리기** 때문이다 — 쪼개기가 틀렸으면 조각이
# 원문에 없고, 결과는 쪼개기 전과 같다.
_DETAIL_PART_SPLIT_RE = re.compile(r"[;；,，]")
# [재현 2026-09-15, 골든 17개 실측] 기업규모는 원문이 "「중소기업기본법」 제2조에 따른 소기업자
# 또는 「…특별조치법」 제2조에 따른 소상공인" 처럼 법령 인용을 사이에 끼고 나열되는데, 모델은
# "소기업자 또는 소상공인" 으로 인용을 빼고 적는다. 조각은 다 원문에 있는데 이어붙인 문자열이
# 없어 DETAIL_NOT_FOUND 로 버려졌고, 그것이 실행마다 있다 없다 해서 흔들렸다(01694234 0건).
# 규모 낱말은 닫힌 어휘라 '또는·및' 로도 쪼개서 조각마다 확인한다 — 이 필드에만 쓴다.
_SIZE_DETAIL_SPLIT_RE = re.compile(r"[;；,，·ㆍ]|또는|및|\s와\s|\s과\s")
_SIZE_DETAIL_FIELDS = ("기업규모_raw",)


def _detail_parts(detail: str, field_name: str | None = None) -> list[str]:
    splitter = _SIZE_DETAIL_SPLIT_RE if field_name in _SIZE_DETAIL_FIELDS else _DETAIL_PART_SPLIT_RE
    parts = [part.strip() for part in splitter.split(detail)]
    return [part for part in parts if part] or [detail]


def _notice_haystack(chunks: list[dict[str, Any]]) -> str:
    """선별된 청크 전체를 이어붙인 비교용 본문.

    청크 경계는 우리가 자른 것이지 공고가 나눈 것이 아니다. 세부 조건이 옆 청크에 있다고
    해서 그 공고에 없는 말이 되지는 않는다.
    """
    return "".join(_squash(chunk.get("text") or "") for chunk in chunks)


def validate_extracted_slot(
    slot: dict[str, Any],
    chunks: list[dict[str, Any]],
    *,
    notice_text: str | None = None,
) -> tuple[bool, str, dict[str, Any] | None]:
    """Reject unsupported source text; clear unverified document locations.

    [재현 2026-09-14] 세부 조건을 **raw 가 들어 있던 청크 하나에서만** 찾고 있었다.
    같은 공고를 세 번 돌린 실측에서 「다. 입찰 공고일 기준 2년 내에 2개 이상 각
    단체급식소…」 조항이 한 번은 요건으로 올라가고 두 번은 DETAIL_NOT_FOUND_IN_SOURCE 로
    버려졌다. 모델이 세부 조건을 어디까지 끊어 적느냐에 따라 그 문자열이 옆 청크로
    넘어가기 때문이다. 청크 경계는 우리가 자른 것이고, 공고가 나눈 것이 아니다.

    그래서 **공고 전체**에서 찾는다. 공고 어디에도 없는 세부 조건은 여전히 버린다 —
    지어낸 값을 판정에 넣지 않는다는 원칙은 그대로다. 넓어진 것은 "어디서 찾는가" 이지
    "무엇을 받아주는가" 가 아니다.
    """
    raw = (slot.get("raw") or "").strip()
    if not raw:
        return False, "raw 비어 있음", None

    source_chunk = _find_source_chunk(raw, chunks)
    if source_chunk is None:
        return False, "raw가 본문에 존재하지 않음(과잉 추출 의심)", None
    # 원문에 있는 것이 확인됐으니, 저장되는 raw 는 줄바꿈·쪽 번호를 걷어낸 모양으로 둔다.
    slot["raw"] = join_wrapped_lines(raw)

    source_original = source_chunk.get("text") or ""
    source_text = _squash(source_original)
    haystack = _notice_haystack(chunks) if notice_text is None else notice_text
    for field_name in _DETAIL_RAW_FIELDS:
        detail = (slot.get(field_name) or "").strip()
        if not detail:
            continue
        # 모델이 적은 글자를 그대로 저장하지 않는다. 원문의 실제 구간으로 바꿔 넣는다 —
        # 같은 구간을 가리키면 모델이 뭐라고 적었든 같은 글자가 남는다.
        snapped = snap_to_source_span(
            detail, source_original, whole_sentence=field_name in _SENTENCE_LEVEL_FIELDS
        )
        if snapped:
            slot[field_name] = snapped
            continue
        squashed_whole = _squash(detail)
        if squashed_whole and squashed_whole in haystack:
            slot.setdefault("_details_found_outside_source_chunk", []).append(field_name)
            continue
        for part in _detail_parts(detail, field_name):
            squashed = _squash(part)
            if not squashed or squashed in source_text:
                continue
            if squashed in haystack:
                # 같은 공고 안의 다른 청크에 있다. 어디서 확인했는지는 남긴다.
                slot.setdefault("_details_found_outside_source_chunk", []).append(field_name)
                continue
            # 무엇이 걸렸는지 남긴다. "세부 조건을 못 찾았다" 만으로는 모델이 지어낸 것인지
            # 우리 대조가 못 따라간 것인지 가릴 수 없고, 둘은 고칠 자리가 다르다.
            slot["_rejected_detail"] = {"field": field_name, "value": detail, "part": part}
            return False, f"{field_name}가 본문에 존재하지 않음(과잉 추출 의심)", source_chunk

    reference = slot.get("근거조항")
    if reference:
        kind = classify_clause_reference(str(reference), chunks, source_chunk)
        slot["_reference_kind"] = kind
        if kind == "STATUTE":
            slot["_statute_reference"] = str(reference)
            slot["근거조항"] = None
        elif kind == "UNVERIFIED":
            slot["근거조항"] = None

    return True, "", source_chunk


def _rejection_reason_code(reason: str) -> str:
    if reason == "raw 비어 있음":
        return "MISSING_RAW"
    if reason.startswith("raw가 본문에 존재하지 않음"):
        return "RAW_NOT_FOUND_IN_SOURCE"
    if "_raw가 본문에 존재하지 않음" in reason:
        return "DETAIL_NOT_FOUND_IN_SOURCE"
    return "SOURCE_VALIDATION_FAILED"


def build_extraction_body(chunks: list[dict[str, Any]], *, max_chars: int | None = 32_000) -> str:
    parts: list[str] = []
    for chunk in chunks:
        document_id = _chunk_document_id(chunk) or "(문서미상)"
        clause_label = chunk.get("clause_label") or "(라벨없음)"
        parts.append(f"[문서 {document_id} | 조항 {clause_label}]\n{chunk.get('text') or ''}")
    return "\n\n".join(parts)[:max_chars]


def extract_legacy_slots(chunks: list[dict[str, Any]], *, structured_extract: StructuredExtractor, max_retry: int = 1) -> dict[str, Any]:
    """Run structured extraction and source-grounding validation."""
    target = select_eligibility_chunks(chunks)
    full_body = build_extraction_body(target, max_chars=None)
    body = full_body[:32_000]
    last_notes = ""
    last_rejected: list[dict[str, str]] = []

    for attempt in range(max_retry + 1):
        try:
            result = structured_extract(SYSTEM_PROMPT, body, SLOT_SCHEMA)
        except Exception as error:
            return {"slots": [], "dropped_requirements": last_rejected, "status": "failed", "notes": f"구조화 추출 호출 실패: {type(error).__name__}", "target_chunk_ids": [chunk.get("chunk_id") for chunk in target]}

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        requirements = result.get("requirements", []) if isinstance(result, dict) else []
        notice_text = _notice_haystack(target)  # 슬롯마다 다시 만들지 않는다

        for extracted in requirements:
            slot = dict(extracted)
            valid, reason, source_chunk = validate_extracted_slot(
                slot, target, notice_text=notice_text
            )
            if not valid:
                record = {
                    "raw": str(slot.get("raw") or ""),
                    "reason_code": _rejection_reason_code(reason),
                }
                detail = slot.get("_rejected_detail")
                if detail:
                    record["detail_field"] = str(detail.get("field") or "")
                    record["detail_value"] = str(detail.get("value") or "")
                rejected.append(record)
                continue
            if source_chunk is not None:
                slot["_source_chunk_id"] = source_chunk.get("chunk_id")
                slot["_source_blocks"] = list(source_chunk.get("source_blocks") or [])
            accepted.append(slot)

        if rejected:
            last_rejected = rejected

        if accepted or not requirements:
            reported_rejections = rejected or (last_rejected if not requirements else [])
            truncated = len(full_body) > len(body)
            notes = ([f"검증 탈락 {len(reported_rejections)}건"] if reported_rejections else [])
            if truncated:
                notes.append("입력 길이 제한으로 선택된 원문 일부를 분석하지 못했습니다.")
            return {"slots": accepted, "dropped_requirements": reported_rejections, "status": "partial" if reported_rejections or truncated else "ok", "notes": " ".join(notes), "target_chunk_ids": [chunk.get("chunk_id") for chunk in target]}

        last_notes = f"전 슬롯 검증 탈락(시도 {attempt + 1})"

    return {"slots": [], "dropped_requirements": last_rejected, "status": "failed", "notes": last_notes, "target_chunk_ids": [chunk.get("chunk_id") for chunk in target]}
