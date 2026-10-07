"""닫힌 값 먼저(closed_first, B안): 닫힌 값은 코드가 찾고, 모델은 조항마다 한 번 그 값의 역할만 정한다.

왜
--
조항 단위 추출(clause)에서는 모델이 슬롯 유형(업종/등록/면허/인증/지역/기타)을 고르고, 코드가 그 선택을 다시
뒤집었다. 2026-10-06 세션의 수정 대부분이 "모델이 어떤 유형을 골랐든 원문에서 닫힌 값을 다시 읽는" 패치였다
(업종 이름이 등록요건으로, 소재지 조항이 기타요건으로, 품명번호가 이름 문자열 속으로). 닫힌 값을 코드가 확정한다면
모델에게 그 유형을 고르게 할 이유가 없다.

흐름
----
1. 조항 고르기는 clause 방식과 같다(select_clauses).
2. 코드가 조항에서 닫힌 값 후보를 사전으로 모두 찾는다 — 지역(시·도, 시·군·구), 업종코드(띄어 쓴 숫자 포함),
   업종 이름(업종 사전), 품명번호(10자리), 기업 규모 낱말.
3. 모델은 조항마다 한 번: 조항의 극성, 후보마다 역할(REQUIRED / ALTERNATIVE+group / EXCLUDED / NOT_RELATED),
   그리고 후보로 표현되지 않는 열린 조건(실적·인력·인증·면허)만 낸다.
4. 코드가 역할대로 요건을 만든다. 닫힌 값 요건은 유형 재분류와 낱말 가드를 거치지 않는다(_CLOSED 슬롯).
   열린 조건만 기존 변환을 탄다.
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

from bidengine.clauses.enumerate import Clause
from bidengine.judgment.clause_safety import guard_reasons, strip_decorations
from bidengine.judgment.context_guard import _NEGATION_VETO_RE
from bidengine.labeling.clause_labeling import CLAUSE_SCHEMA, select_clauses
from bidengine.labeling.clause_polarity import POLARITIES
from bidengine.labeling.requirement_extraction import (
    StructuredExtractor,
    _notice_haystack,
    _rejection_reason_code,
    section_paths,
    validate_extracted_slot,
)
from bidengine.normalization.region_vocab import SIGUNGU_PARENTS
from bidengine.normalization.regions import SIDO_CANONICAL, find_regions
from bidengine.ports import IndustryNameResolver
from bidengine.requirements.legacy_slots import (
    _NAMED_INDUSTRY_CODE_RE,
    _PRODUCT_CODE_RE,
    _PRODUCT_CONTEXT_RE,
    _SIZE_WORD_RE,
    _compact,
    _size_text,
    company_size_alias,
    industry_code_for_name,
    is_common_disqualification,
    labelled_industry_codes,
)

CLOSED_FIRST_VERSION = "closed-first-v1"
MAX_BODY_CHARS = 24_000
ROLES = ("REQUIRED", "ALTERNATIVE", "EXCLUDED", "NOT_RELATED")
_PARTY_CLAUSE_RE = re.compile(r"공동\s*(?:수급|계약|도급|이행)|분담\s*이행")
_PARTY_PROCEDURE_RE = re.compile(r"협정서|제출|승인|서식|간주")
_INDUSTRY_NAME_SPAN_RE = re.compile(r"[가-힣][가-힣·ㆍ∙․]{1,24}업")
_BRACKET_INDUSTRY_CODE_RE = re.compile(r"업\s*(?:\([^()]{0,20}\))?\s*[\[［]\s*([0-9]{4})\s*[\]］]")
# "다음 각 호 어느 하나에 해당하는 경우" 아래로 이어지는 하위 조항 표식(㉮ ㉯, ⓐ, (가), 가), ①).
_SUB_ITEM_RE = re.compile(r"^\s*(?:[㉮-㉻]|[ⓐ-ⓩ]|\([가-하]\)|[가-하]\)|[①-⑳])")
_UMBRELLA_RE = re.compile(r"(?:중|가운데)\s*(?:하나|어느|1\s*개|택)|어느\s*하나|택\s*1|택일|각\s*호의\s*(?:1|어느)")
_REGION_NARROWING_RE = re.compile(r"(?:동|서|남|북|중)부|영동|영서|권역|도서지역")
_PROCEDURAL_POLARITIES = {"NOT_REQUIREMENT", "EVALUATION"}
# 열린 조건(등록·인증·면허 이름)으로 받지 않는 이름: 법령·절차 문구와 나라장터 등록 낱말. 모델이 이런 구간을
# 실행마다 다르게 잘라 와 결과가 흔들렸다("제14조에의한자격요건" / "제14조", "이용자등록", "구매및제조물품").
_OPEN_NAME_NOISE_RE = re.compile(
    r"제\s*\d+\s*조|시행\s*(?:령|규칙)|법률|규정|자격\s*요건|입찰\s*참가|이용자\s*등록|나라장터|조달청|"
    r"국가종합전자조달|전자입찰|구매\s*및\s*제조|제조\s*(?:또는|및)\s*공급|물품으로"
)


def open_name_is_noise(name: str, clause: str, candidates: list["Candidate"]) -> str | None:
    """열린 조건의 이름을 버릴 이유. 버리지 않으면 None."""
    from bidengine.requirements.legacy_slots import is_generic_registration_name

    compact = _compact(name)
    if not compact or is_generic_registration_name(name):
        return "GENERIC_NAME"
    if _OPEN_NAME_NOISE_RE.search(name):
        return "STATUTE_OR_PROCEDURE"
    if any(c.kind == "PRODUCT" for c in candidates) and not re.search(r"\d", name) and len(compact) <= 15:
        # 품명번호 조항의 물품 이름("사격총(세부품명번호 4918169801)") — 품명번호 요건과 같은 요건이다.
        return "PRODUCT_NAME_DUPLICATE"
    return None


@dataclass(frozen=True)
class Candidate:
    id: str
    kind: str      # REGION | INDUSTRY | PRODUCT | SIZE
    value: str     # 정규 값: "전북특별자치도 전주시", "1468", "4320140101", "소기업"
    surface: str   # 원문에서 찾은 표기


def scan_candidates(text: str, resolver: IndustryNameResolver | None) -> list[Candidate]:
    """조항에서 닫힌 값 후보를 모두 찾는다. 요건인지는 모르는 채로 — 그 판단은 모델이 한다."""
    found: list[tuple[str, str, str]] = []
    plain = strip_decorations(text or "")
    compact = _compact(text or "")

    sidos, subs = find_regions(plain)
    used_sidos: set[str] = set()
    for sub in subs:
        parents = {SIDO_CANONICAL.get(p, p) for p in SIGUNGU_PARENTS.get(sub, ())}
        parent = next((s for s in sidos if s in parents), None)
        if parent:
            used_sidos.add(parent)
        found.append(("REGION", f"{parent} {sub}" if parent else sub, sub))
    for sido in sidos:
        if sido not in used_sidos:
            found.append(("REGION", sido, sido))

    codes: dict[str, str] = {}
    for code in sorted(labelled_industry_codes(text)):
        codes.setdefault(code, f"업종코드 {code}")
    for code in _NAMED_INDUSTRY_CODE_RE.findall(compact):
        codes.setdefault(code, code)
    for code in _BRACKET_INDUSTRY_CODE_RE.findall(plain):
        # "폐기물중간처분업(지정폐기물)[1254]" — '업종코드' 낱말 없이 이름 뒤 대괄호에 쓴 업종코드.
        codes.setdefault(code, f"[{code}]")
    for match in _INDUSTRY_NAME_SPAN_RE.finditer(plain):
        code = industry_code_for_name(match.group(0), resolver)
        if code:
            codes.setdefault(code, match.group(0))
    for code, surface in codes.items():
        found.append(("INDUSTRY", code, surface))

    if _PRODUCT_CONTEXT_RE.search(text or ""):
        for code in dict.fromkeys(_PRODUCT_CODE_RE.findall(compact)):
            found.append(("PRODUCT", code, code))

    for word in dict.fromkeys(_SIZE_WORD_RE.findall(_size_text(text or ""))):
        found.append(("SIZE", word, word))

    seen: set[tuple[str, str]] = set()
    out: list[Candidate] = []
    for kind, value, surface in found:
        if (kind, value) in seen:
            continue
        seen.add((kind, value))
        out.append(Candidate(id=f"V{len(out) + 1}", kind=kind, value=value, surface=surface))
    return out


_KIND_LABEL = {"REGION": "지역", "INDUSTRY": "업종코드", "PRODUCT": "품명번호", "SIZE": "기업규모"}


def _schema() -> dict[str, Any]:
    open_item = CLAUSE_SCHEMA["schema"]["properties"]["clauses"]["items"]["properties"]["requirements"]["items"]
    return {
        "name": "closed_first",
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
                            "polarity": {"type": "string", "enum": list(POLARITIES)},
                            "candidates": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "id": {"type": "string"},
                                        "role": {"type": "string", "enum": list(ROLES)},
                                        "group": {"type": "string"},
                                    },
                                    "required": ["id", "role", "group"],
                                },
                            },
                            "open_requirements": {"type": "array", "items": open_item},
                        },
                        "required": ["clause_id", "polarity", "candidates", "open_requirements"],
                    },
                }
            },
            "required": ["clauses"],
        },
    }


SCHEMA = _schema()

SYSTEM_PROMPT = """너는 입찰공고의 참가자격 조항을 읽는 도구다. 조항은 [C001] 같은 id 로 주어지고, 각 조항에는 그것이 놓인 절의 위치와, 코드가 조항에서 찾은 값 후보(지역·업종코드·품명번호·기업규모)가 V1, V2 … 로 붙어 있다.

조항마다 세 가지를 낸다.
1. polarity: 조항이 업체에 무엇을 요구하는지.
   - POSITIVE: 업체가 갖추어야 하는 자격을 정한다. 문장 속 '또는'·'다만'·괄호가 서류나 대상 범위를 설명할 뿐이면 POSITIVE 다.
   - EXCLUSION: 해당하는 업체는 참가할 수 없다고 정한다.
   - EXCEPTION: 단서·예외 때문에 일부 업체에는 요건이 적용되지 않거나 다른 것으로 갈음된다.
   - EVALUATION: 참가 자격이 아니라 평가·심사·배점 기준이다.
   - NOT_REQUIREMENT: 업체의 자격이 아니다(절차·일정·제출 서류, 납품 물품의 조건, 계약 후 과업 수행 조건, 투입 인력 조건).
   - UNSURE: 분명하지 않다.
2. candidates: 받은 후보마다 role 을 고른다. 받은 id 를 그대로 쓰고, 받은 후보는 모두 답한다.
   - REQUIRED: 참가 업체가 갖추어야 하는 값이다(소재지, 등록 업종, 등록 물품, 기업 규모).
   - ALTERNATIVE: '또는'으로 나열된 대안 중 하나다. 같은 대안 묶음끼리 같은 group 이름(G1, G2 …)을 쓴다.
   - EXCLUDED: 이 값에 해당하면 참가할 수 없다(예: 대기업 참여 제한).
   - NOT_RELATED: 요건과 무관하다(납품·수행 장소, 발주기관·학교 이름, 법령 이름 속 낱말, 평가 기준).
   group 은 ALTERNATIVE 일 때만 쓰고, 나머지는 빈 문자열이다.
3. open_requirements: 후보로 표현되지 않는 참가 자격만 낸다(실적, 인력, 인증·면허·등록 이름). 지역·업종·품명번호·기업규모는 후보로 이미 받았으므로 여기에 내지 않는다. 각 *_raw 필드는 그 조항 안의 연속된 구간을 그대로 복사한다. 없으면 빈 배열이다.

규칙: 원문을 쓰지 않는다. 확신이 없으면 polarity 를 UNSURE 로 둔다. 받은 clause_id 를 그대로 쓴다."""


def _key(section: str, text: str) -> str:
    return hashlib.sha256((CLOSED_FIRST_VERSION + "\n" + section + "\n" + "".join((text or "").split())).encode("utf-8")).hexdigest()[:24]


def _entry_body(clause_id: str, section: str, clause: Clause, candidates: list[Candidate]) -> str:
    listed = "; ".join(f"{c.id} {_KIND_LABEL[c.kind]} {c.value}" + (f" (원문: {c.surface})" if c.surface != c.value else "") for c in candidates)
    return f"[{clause_id}] 위치: {section or '알 수 없음'} | 후보: {listed or '없음'}\n{clause.text}"


def _closed_requirements(polarity: str, text: str, candidates: list[Candidate], roles: dict[str, tuple[str, str]]) -> tuple[list[dict], list[dict]]:
    """역할을 받은 후보로 요건(정의)과 진단을 만든다."""
    reqs: list[dict] = []
    diags: list[dict] = []
    by_role = {role: [c for c in candidates if roles.get(c.id, ("NOT_RELATED", ""))[0] == role] for role in ROLES}

    if polarity == "EXCLUSION":
        excluded_sizes = [c.value for c in by_role["EXCLUDED"] if c.kind == "SIZE"]
        if excluded_sizes and set(excluded_sizes) <= {"대기업", "중견기업"}:
            reqs.append({"type": "COMPANY_SIZE", "value": " 및 ".join(excluded_sizes), "scope": {"restriction": "EXCLUDE"}})
        elif is_common_disqualification(text):
            # 부정당업자·조세포탈처럼 모든 입찰자에게 똑같이 걸리는 결격 — 회사 프로필과 대조할 자격이 아니다(clause 방식과 같은 기준).
            diags.append({"code": "UNMAPPED_REQUIREMENT", "raw": text, "reason": "COMMON_DISQUALIFICATION"})
        else:
            diags.append({"code": "UNMAPPED_REQUIREMENT", "raw": text, "reason": "MODEL_POLARITY_EXCLUSION"})
        return reqs, diags
    if polarity != "POSITIVE":
        if not candidates and len(_compact(text)) <= 20 and not re.search(r"[.。]|이어야|하여야|한다|합니다", text):
            # 값도 서술도 없는 절 제목("3. 입찰참가 자격") — 요건이 아니다.
            diags.append({"code": "CLAUSE_NOT_LABELLED", "raw": text, "reason": "HEADING"})
        else:
            diags.append({"code": "UNMAPPED_REQUIREMENT", "raw": text, "reason": f"MODEL_POLARITY_{polarity}"})
        return reqs, diags

    wanted = by_role["REQUIRED"] + by_role["ALTERNATIVE"]
    if wanted and _NEGATION_VETO_RE.search(strip_decorations(text)):
        # 모델은 요구라는데 문장에 부정 낱말이 있다 — 이견이라 확정하지 않는다.
        diags.append({"code": "UNMAPPED_REQUIREMENT", "raw": text, "reason": "POLARITY_DISAGREEMENT"})
        return reqs, diags

    sizes = [c for c in wanted if c.kind == "SIZE"]
    if sizes:
        alias = company_size_alias(" ".join(c.value for c in sizes))
        if alias:
            reqs.append({"type": "COMPANY_SIZE", "value": alias, "scope": {}})
        else:
            diags.append({"code": "UNMAPPED_COMPANY_SIZE", "raw": text, "reason": "SIZE_UNION_UNKNOWN"})

    def build(c: Candidate) -> dict | None:
        if c.kind == "REGION":
            if _REGION_NARROWING_RE.search(text) and " " not in c.value:
                diags.append({"code": "UNMAPPED_REGION", "raw": text, "reason": "REGION_NARROWED"})
                return None
            return {"type": "REGION", "value": c.value, "scope": {}}
        if c.kind == "INDUSTRY":
            return {"type": "INDUSTRY", "value": c.value, "scope": {"industry_name": c.surface}}
        if c.kind == "PRODUCT":
            return {"type": "REGISTRATION_CERTIFICATION", "value": c.value, "scope": {"kind": "REGISTRATION", "source_name": c.surface}}
        return None

    for c in by_role["REQUIRED"]:
        item = build(c)
        if item:
            reqs.append(item)
    groups: dict[str, list[Candidate]] = {}
    for c in by_role["ALTERNATIVE"]:
        if c.kind != "SIZE":
            groups.setdefault(roles[c.id][1] or "G", []).append(c)
    for name, members in groups.items():
        built = [b for b in (build(c) for c in members) if b]
        if len(built) == 1:
            reqs.append(built[0])
        elif built:
            reqs.extend({**b, "group": name} for b in built)
    return reqs, diags


def _merge_cross_clause_alternatives(kept: list[Clause], slots: list[dict[str, Any]]) -> None:
    """'다음 각 호 어느 하나에 해당하는 경우' 아래 하위 조항(㉮ ㉯ …)이 따로 떨어진 조항이면, 그 조항들은 서로 대안이다.

    조항을 하나씩 읽으면 ㉯ 의 업종들이 필수가 되어 ㉮ 를 갖춘 회사가 부적합이 된다(2026-10-06 표본 g 고양 복지회관).
    갈래마다 요건 단위(요건 하나, 또는 대안 묶음 하나)가 하나면 모두 한 대안 묶음으로 합친다. 한 갈래에 요건이
    여럿이면("A 와 B 와 C 를 모두") 지금 구조로 '(갈래1) 또는 (갈래2 전부)' 를 담을 수 없으므로 확인 필요로 둔다.
    """
    closed = {}
    for slot in slots:
        if slot.get("유형") == "_CLOSED":
            closed.setdefault(_compact(slot.get("raw") or ""), slot)
    texts = [clause.text for clause in kept]
    handled: set[str] = set()
    for index, text in enumerate(texts):
        if not _UMBRELLA_RE.search(text):
            continue
        branch_texts = [text]
        for follower in texts[index + 1:]:
            if not _SUB_ITEM_RE.match(follower):
                break
            branch_texts.append(follower)
        if len(branch_texts) < 2:
            continue
        keys = [_compact(t) for t in branch_texts]
        if any(k in handled for k in keys):
            continue
        branches = [closed.get(k) for k in keys]
        units = []
        for slot in branches:
            reqs = [r for r in (slot or {}).get("_closed_requirements") or [] if not (r.get("scope") or {}).get("restriction")]
            groups = {r.get("group") for r in reqs if r.get("group")}
            singles = [r for r in reqs if not r.get("group")]
            units.append(len(singles) + len(groups))
        if all(count == 0 for count in units):
            continue
        handled.update(keys)
        # 같은 원문이 다른 문서(HWP·PDF)에도 있으면 함께 고친다.
        targets = [slot for slot in slots if slot.get("유형") == "_CLOSED" and _compact(slot.get("raw") or "") in set(keys)]
        if all(count <= 1 for count in units):
            group = f"X{index}"
            for slot in targets:
                slot["_closed_requirements"] = [
                    {**r, "group": group} if not (r.get("scope") or {}).get("restriction") else r
                    for r in slot.get("_closed_requirements") or []
                ]
        else:
            for slot in targets:
                kept_reqs = [r for r in slot.get("_closed_requirements") or [] if (r.get("scope") or {}).get("restriction")]
                if len(kept_reqs) != len(slot.get("_closed_requirements") or []):
                    slot["_closed_requirements"] = kept_reqs
                    slot["_closed_diagnostics"] = [*(slot.get("_closed_diagnostics") or []),
                                                   {"code": "UNMAPPED_REQUIREMENT", "raw": slot["raw"], "reason": "CROSS_CLAUSE_ALTERNATIVE"}]


def extract_closed_first(
    chunks: list[dict[str, Any]],
    *,
    structured_extract: StructuredExtractor,
    industry_resolver: IndustryNameResolver | None = None,
    max_retry: int = 1,
    clause_selection: str = "hybrid",
    selection_memory: MutableMapping[str, bool] | None = None,
    memory: MutableMapping[str, Any] | None = None,
    votes: int = 1,
) -> dict[str, Any]:
    """votes: 조항을 처음 물을 때 같은 질문을 몇 번 보내 다수결로 정할지. 기억에 있는 조항은 묻지 않는다."""
    kept, target, base, selection_note = select_clauses(
        chunks, structured_extract=structured_extract, max_retry=max_retry,
        clause_selection=clause_selection, selection_memory=selection_memory,
    )
    paths = section_paths(chunks)
    known: MutableMapping[str, Any] = memory if memory is not None else {}
    notice_text = _notice_haystack(target)

    prepared = []
    for clause in kept:
        section = paths.get(str(clause.chunk_id), "")
        prepared.append((clause, section, scan_candidates(clause.text, industry_resolver), _key(section, clause.text)))

    pending = [item for item in prepared if item[3] not in known]
    answers: dict[str, dict] = {}
    last_error = ""
    failed = False
    batch: list = []
    size = 0

    def flush() -> None:
        nonlocal batch, size, last_error, failed
        if not batch:
            return
        ids = {f"C{index:03d}": item for index, item in enumerate(batch, start=1)}
        body = "\n\n".join(_entry_body(cid, item[1], item[0], item[2]) for cid, item in ids.items())
        samples: list[dict[str, dict]] = []
        for _vote in range(max(1, votes)):
            result = None
            for _attempt in range(max_retry + 1):
                try:
                    result = structured_extract(SYSTEM_PROMPT, body, SCHEMA)
                    break
                except Exception as error:  # noqa: BLE001 - 호출 실패는 결과 상태로 알린다
                    last_error = f"구조화 추출 호출 실패: {type(error).__name__}"
            if result is None:
                continue
            parsed: dict[str, dict] = {}
            for entry in (result.get("clauses") or []) if isinstance(result, dict) else []:
                item = ids.get(str(entry.get("clause_id") or ""))
                if item is not None:
                    parsed[item[3]] = {
                        "polarity": entry.get("polarity") if entry.get("polarity") in POLARITIES else "UNSURE",
                        "roles": {str(c.get("id")): [c.get("role") if c.get("role") in ROLES else "NOT_RELATED", str(c.get("group") or "")]
                                  for c in entry.get("candidates") or []},
                        "open": [dict(x) for x in entry.get("open_requirements") or []],
                    }
            for cid, item in ids.items():  # 응답에 없는 조항은 '요건 아님'
                parsed.setdefault(item[3], {"polarity": "NOT_REQUIREMENT", "roles": {}, "open": []})
            samples.append(parsed)
        if not samples:
            failed = True
        else:
            # 조항마다 다수결: 극성과 후보 역할(묶음 이름은 무시)이 같은 답끼리 세어 가장 많은 답을 쓴다. 같으면 먼저 받은 답.
            for _cid, item in ids.items():
                options = [sample[item[3]] for sample in samples]
                signatures = [(o["polarity"], tuple(sorted((k, v[0]) for k, v in o["roles"].items()))) for o in options]
                best = max(range(len(options)), key=lambda i: (signatures.count(signatures[i]), -i))
                answers[item[3]] = options[best]
        batch, size = [], 0

    for item in pending:
        length = len(item[0].text) + 60 * (len(item[2]) + 1)
        if batch and size + length > MAX_BODY_CHARS:
            flush()
        batch.append(item)
        size += length
    flush()
    if failed and not answers and pending:
        return {**base, "slots": [], "dropped_requirements": [], "status": "failed", "notes": last_error,
                "candidate_count": 0, "clause_texts": [c.text for c in kept]}

    slots: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    candidates_total = 0
    for clause, section, candidates, key in prepared:
        answer = known[key] if key in known else answers.get(key)
        if answer is None:  # 호출 실패로 답이 없는 조항
            slots.append({"유형": "_CLOSED", "raw": clause.text, "_closed_requirements": [],
                          "_closed_diagnostics": [{"code": "UNMAPPED_REQUIREMENT", "raw": clause.text, "reason": "MODEL_POLARITY_UNSURE"}],
                          "_clause_id": clause.clause_id, "_source_chunk_id": clause.chunk_id, "_source_blocks": list(clause.source_blocks)})
            continue
        polarity = answer["polarity"]
        roles = {cid: (role, group) for cid, (role, group) in answer["roles"].items()}
        source = {"_clause_id": clause.clause_id, "_source_chunk_id": clause.chunk_id, "_source_blocks": list(clause.source_blocks),
                  "_section_path": section, "근거조항": None}
        if _PARTY_CLAUSE_RE.search(clause.text) and not _PARTY_PROCEDURE_RE.search(clause.text):
            slots.append({"유형": "_CLOSED", "raw": clause.text, "_closed_requirements": [],
                          "_closed_diagnostics": [{"code": "UNMAPPED_REQUIREMENT", "raw": clause.text, "reason": "COMPOSITE_PARTY_RULE"}], **source})
            continue
        reqs, diags = _closed_requirements(polarity, clause.text, candidates, roles)

        clause_rejected = False
        open_slots = []
        kept_open: list[dict] = []
        closed_values = {c.value for c in candidates}
        for labelled in answer["open"] if polarity == "POSITIVE" else []:
            if labelled.get("유형") in {"지역요건", "업종요건", "기업규모요건"}:
                continue
            name = str(labelled.get("등록인증_raw") or "")
            if name and any(v in _compact(name) for v in closed_values if v.isdigit()):
                kept_open.append(labelled)
                continue  # 후보로 이미 담은 번호
            if labelled.get("유형") in {"등록요건", "인증요건", "면허요건"}:
                noise = open_name_is_noise(name, clause.text, candidates)
                industry_values = {c.value for c in candidates if c.kind == "INDUSTRY"}
                if not noise and industry_values and industry_code_for_name(name, industry_resolver) in industry_values:
                    noise = "INDUSTRY_DUPLICATE"   # "전기공사업의 등록" — 같은 조항 업종 요건과 같은 요건
                if not noise and "직접생산" in _compact(name) and any(c.kind == "PRODUCT" for c in candidates):
                    noise = "PRODUCT_DUPLICATE"    # 품명번호 요건의 증명서 이름
                if noise:
                    kept_open.append(labelled)
                    diags.append({"code": "CLAUSE_NOT_LABELLED", "raw": clause.text, "reason": f"OPEN_NAME_{noise}"})
                    continue
            slot = {**dict(labelled), "raw": clause.text, **source, "_clause_polarity": "POSITIVE"}
            candidates_total += 1
            valid, reason, _chunk = validate_extracted_slot(slot, target, notice_text=notice_text)
            if not valid:
                clause_rejected = True
                rejected.append({"raw": clause.text, "reason_code": _rejection_reason_code(reason)})
                continue
            kept_open.append(labelled)
            open_slots.append(slot)

        if not reqs and not diags and not open_slots and polarity == "POSITIVE":
            # 요구라는데 담을 값이 없다 — 공통 결격·법령 절차면 제외로, 아니면 표현 못 한 요건(공백)으로 남긴다.
            if is_common_disqualification(clause.text):
                diags.append({"code": "UNMAPPED_REQUIREMENT", "raw": clause.text, "reason": "COMMON_DISQUALIFICATION"})
            elif "LEGAL_PROCEDURAL_RULE" in guard_reasons(clause.text):
                diags.append({"code": "UNMAPPED_REQUIREMENT", "raw": clause.text, "reason": "LEGAL_PROCEDURAL_RULE"})
            else:
                diags.append({"code": "UNMAPPED_REQUIREMENT", "raw": clause.text})
        if reqs or diags:
            slots.append({"유형": "_CLOSED", "raw": clause.text, "_closed_requirements": reqs, "_closed_diagnostics": diags, **source})
        slots.extend(open_slots)
        candidates_total += len(reqs)
        if key not in known and key in answers:
            # 답을 기억한다. 검증에서 탈락한 열린 조건만 빼고 — 탈락한 답을 통째로 기억하지 않으면 그 조항은 다음
            # 분석에서 다시 묻게 되어 다른 답을 받는다(일관성이 깨진다). 탈락한 슬롯은 어차피 요건이 되지 않는다.
            known[key] = {**answers[key], "open": kept_open} if clause_rejected else answers[key]

    _merge_cross_clause_alternatives(kept, slots)

    notes = [selection_note] if selection_note else []
    if rejected:
        notes.append(f"검증 탈락 {len(rejected)}건")
    if base["input_truncated"]:
        notes.append("입력 길이 제한으로 뒤쪽 조항을 분석하지 못했습니다.")
    return {
        **base,
        "slots": slots,
        "dropped_requirements": rejected,
        "status": "partial" if rejected or base["input_truncated"] or failed else "ok",
        "notes": " ".join(notes) + (f" {last_error}" if failed else ""),
        "candidate_count": candidates_total,
        "clause_texts": [clause.text for clause in kept],
        "labels_reused": len(prepared) - len(pending),
    }
