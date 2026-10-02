"""조항 단위 라벨링 (S3). 경계와 원문은 코드가 정하고, 모델은 조항마다 요건 슬롯만 붙인다.

extract_legacy_slots 와 같은 모양의 결과를 돌려주므로 이후 정규화·대안·판정 경로는 그대로다.
차이는 둘이다.
  - 모델은 raw 를 쓰지 않는다. 슬롯의 raw 는 조항 원문이다. 실행마다 같은 조항은 같은 raw 다.
  - 모델은 조항을 합치거나 나눌 수 없다. 응답에 없는 조항 id 는 "요건 아님" 이다.
"""
from __future__ import annotations

import copy
import re
from typing import Any

from collections.abc import MutableMapping

from bidengine.clauses.enumerate import Clause, enumerate_clauses
from bidengine.labeling.clause_selection import select_requirement_clauses, selection_key
from bidengine.labeling.requirement_extraction import (
    SLOT_SCHEMA,
    StructuredExtractor,
    _notice_haystack,
    _rejection_reason_code,
    select_eligibility_chunks_with_mode,
    validate_extracted_slot,
)

MAX_BODY_CHARS = 32_000
# 공동수급·공동계약의 허용 여부를 말하는 조항. 닫힌 낱말이라 코드가 찾는다. 협정서 제출 같은 절차 문장은 아니다.
_PARTY_CLAUSE_RE = re.compile(r"공동\s*(?:수급|계약|도급|이행)|분담\s*이행")
_PARTY_PROCEDURE_RE = re.compile(r"협정서|제출|승인|서식|간주")


def _clause_schema() -> dict[str, Any]:
    item = copy.deepcopy(SLOT_SCHEMA["schema"]["properties"]["requirements"]["items"])
    item["properties"].pop("raw", None)
    item["properties"].pop("근거조항", None)
    item["required"] = [name for name in item["required"] if name not in {"raw", "근거조항"}]
    return {
        "name": "clause_labels",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "clauses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "clause_id": {"type": "string"},
                            "requirements": {"type": "array", "items": item},
                        },
                        "required": ["clause_id", "requirements"],
                    },
                }
            },
            "required": ["clauses"],
        },
    }


CLAUSE_SCHEMA = _clause_schema()

CLAUSE_SYSTEM_PROMPT = """너는 입찰공고의 참가자격 조항에 요건 라벨을 붙이는 도구다. 조항은 이미 [C001] 같은 id 로 나뉘어 있다.
규칙:
1. 조항마다 그 조항이 요구하는 참가자격 요건을 requirements 배열로 낸다. 참가자격이 아닌 조항(제목, 절차 안내, 제출 서류, 무효 안내)은 빈 배열로 둔다.
2. 조항을 합치거나 나누지 마라. 받은 clause_id 를 그대로 쓴다. 없는 id 를 만들지 마라.
3. 원문 문장은 쓰지 않는다. 각 *_raw 필드에는 **그 조항 안에서** 연속된 한 구간을 그대로 복사한다. 해당 표현이 없으면 null.
4. 한 조항에 독립적인 조건이 여럿이면(예: 업종 등록 + 소재지) 각각 별도 requirement 로 낸다.
5. 유형 기준은 다음과 같다. 업종·업태 참가 제한은 업종요건(업종_raw). 등록·면허·인증 보유는 각각 등록요건·면허요건·인증요건(등록인증_raw 에 실제 명칭). 소재지 제한은 지역요건(지역_raw). 규모 제한은 기업규모요건(기업규모_raw). 실적은 실적요건(기간·금액·건수·경험분야·실적기관). 인력은 인력요건(인원_raw, 인력역할_raw).
6. '또는/다만/각 호' 로 결합된 조건, 부정·예외·공동수급 조건을 단순 보유 요건으로 축약하지 마라. 안전하게 표현할 수 없으면 유형=기타요건 으로 둔다. 판단은 코드가 조항 원문을 다시 보고 한다."""


def _body(clauses: list[Clause]) -> str:
    return "\n\n".join(f"[{clause.clause_id}]\n{clause.text}" for clause in clauses)


SELECTION_MODES = ("code", "hybrid", "model")


def extract_clause_slots(
    chunks: list[dict[str, Any]],
    *,
    structured_extract: StructuredExtractor,
    max_retry: int = 1,
    clause_selection: str = "code",
    selection_memory: MutableMapping[str, bool] | None = None,
) -> dict[str, Any]:
    """clause_selection
      code   제목·키워드로 고른 자격 절의 조항 (기본)
      hybrid 코드가 고른 조항 ∪ 모델이 문서 전체에서 고른 조항
      model  모델이 고른 조항만. 모델이 아무것도 고르지 않거나 호출이 실패하면 코드 선택으로 돌아간다.
    """
    if clause_selection not in SELECTION_MODES:
        raise ValueError(f"알 수 없는 조항 선택 방식: {clause_selection}")
    target, selection_mode = select_eligibility_chunks_with_mode(chunks)
    clauses = enumerate_clauses(target)
    selection_note = ""
    if clause_selection != "code":
        document_clauses = enumerate_clauses(chunks)
        picked = select_requirement_clauses(
            document_clauses, structured_extract=structured_extract, memory=selection_memory, max_retry=max_retry
        )
        if picked is None:
            selection_note = "조항 선택 호출이 실패해 코드 선택으로 분석했습니다."
        elif picked or clause_selection == "hybrid":
            code_chunk_ids = {chunk.get("chunk_id") for chunk in target}
            picked_chunk_ids = {c.chunk_id for c in document_clauses if selection_key(c.text) in picked}
            wanted = picked_chunk_ids | code_chunk_ids if clause_selection == "hybrid" else picked_chunk_ids
            target = [chunk for chunk in chunks if chunk.get("chunk_id") in wanted]
            clauses = [
                clause for clause in enumerate_clauses(target)
                if selection_key(clause.text) in picked
                or (clause_selection == "hybrid" and clause.chunk_id in code_chunk_ids)
            ]
            # 모델이 문서 전체의 조항을 보고 골랐다. "자격 절을 봤다" 고 말할 수 있다.
            selection_mode = "anchored"
    full_body = _body(clauses)
    # 조항 단위로 자른다 — 조항 중간에서 끊지 않는다.
    kept: list[Clause] = []
    for clause in clauses:
        if len(_body([*kept, clause])) > MAX_BODY_CHARS:
            break
        kept.append(clause)
    body = _body(kept)
    by_id = {clause.clause_id: clause for clause in kept}
    base = {
        # 모델이 요건으로 올리지 않아도 사람이 봐야 하는 조항. 파이프라인이 확인 필요(공백)로 남긴다.
        "party_clauses": [
            clause.text for clause in kept
            if _PARTY_CLAUSE_RE.search(clause.text) and not _PARTY_PROCEDURE_RE.search(clause.text)
        ],
        "target_chunk_ids": [chunk.get("chunk_id") for chunk in target],
        "selection_mode": selection_mode,
        "input_truncated": len(full_body) > len(body),
        "clause_count": len(kept),
    }

    last_error = ""
    for _attempt in range(max_retry + 1):
        try:
            result = structured_extract(CLAUSE_SYSTEM_PROMPT, body, CLAUSE_SCHEMA)
        except Exception as error:  # noqa: BLE001 - 호출 실패는 결과 상태로 알린다
            last_error = f"구조화 추출 호출 실패: {type(error).__name__}"
            continue

        notice_text = _notice_haystack(target)
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, str]] = []
        candidates = 0
        unknown_ids = 0
        for entry in (result.get("clauses") or []) if isinstance(result, dict) else []:
            clause = by_id.get(str(entry.get("clause_id") or ""))
            if clause is None:
                unknown_ids += 1
                continue
            for labelled in entry.get("requirements") or []:
                candidates += 1
                slot = dict(labelled)
                slot["raw"] = clause.text
                slot["근거조항"] = None
                valid, reason, source_chunk = validate_extracted_slot(slot, target, notice_text=notice_text)
                if not valid:
                    record = {"raw": clause.text, "reason_code": _rejection_reason_code(reason)}
                    detail = slot.get("_rejected_detail")
                    if detail:
                        record["detail_field"] = str(detail.get("field") or "")
                        record["detail_value"] = str(detail.get("value") or "")
                    rejected.append(record)
                    continue
                slot["_clause_id"] = clause.clause_id
                slot["_source_chunk_id"] = clause.chunk_id
                slot["_source_blocks"] = list(clause.source_blocks)
                accepted.append(slot)

        notes = [selection_note] if selection_note else []
        if rejected:
            notes.append(f"검증 탈락 {len(rejected)}건")
        if unknown_ids:
            notes.append(f"없는 조항 id {unknown_ids}건 무시")
        if base["input_truncated"]:
            notes.append("입력 길이 제한으로 뒤쪽 조항을 분석하지 못했습니다.")
        return {
            **base,
            "slots": accepted,
            "dropped_requirements": rejected,
            "status": "partial" if rejected or base["input_truncated"] else "ok",
            "notes": " ".join(notes),
            "candidate_count": candidates,
        }

    return {**base, "slots": [], "dropped_requirements": [], "status": "failed", "notes": last_error, "candidate_count": 0}
