"""Canonical Requirement diff for changed-notice revalidation.

Requirement keys are extraction-order based. Match semantic identities (type +
source-clause skeleton) before positional keys; only unchanged source conditions
may carry answers over. With clause-mode extraction the raw is the source clause
itself, so the identity is a stable anchor across runs (docs/experiments/2026-10-01).
"""
from __future__ import annotations
import re
from typing import Literal
from pydantic import BaseModel
from bidengine.contracts import QualificationRequirement

ChangeType = Literal["UNCHANGED","MODIFIED","ADDED","REMOVED"]

class RequirementChange(BaseModel):
    change_type: ChangeType
    identity: str
    baseline_key: str | None = None
    current_key: str | None = None
    baseline: QualificationRequirement | None = None
    current: QualificationRequirement | None = None

# 조항 앞의 항목 번호·기호. 앞 항목이 하나 빠지면 뒤 항목 번호가 당겨진다(G2 2차: 강원도 조항이
# 빠져 "4) … 1169" 가 "3) … 1169" 가 됐다). 번호는 내용이 아니다.
_ITEM_MARKER_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s*[.)．]|[가-힣]\s*[.)．]|\(\s*(?:\d{1,2}|[가-힣])\s*\)|[①-⑳]|[ㅇ○●◦▶▷□■◆◇\-·•])\s*"
)

def _norm_text(value: object | None)->str:
    if value is None: return ""
    return re.sub(r"\s+","",_ITEM_MARKER_RE.sub("",str(value)).casefold())

def _raw_skeleton(req: QualificationRequirement)->str:
    raw=_norm_text(req.raw)
    value=_norm_text(req.value)
    if value:
        raw=raw.replace(value,"<value>")
    raw=re.sub(r"\d+(?:[.,]\d+)*","<n>",raw)
    raw=re.sub(r"(?:억원|만원|원|개월|년|건|명)","<unit>",raw)
    return raw

def semantic_identity(req: QualificationRequirement)->str:
    scope=req.scope or {}
    stable_scope_parts=[]
    for key in ("kind","role","source","client_requirement"):
        if scope.get(key) not in (None,""):
            stable_scope_parts.append(f"{key}={_norm_text(scope[key])}")
    return "|".join([req.type,*stable_scope_parts,_raw_skeleton(req)])

# 판정에 쓰지 않는 설명용 scope 키. 업종 요건은 코드로 판정하고 industry_name 은 화면 표시용인데,
# 모델이 그 이름을 실행마다 다른 길이로 잘라 온다(G2 실측: "학술·연구용역(업종코드:1169)" ↔
# "…으로 경쟁입찰 참가자격을 등록한 자"). 그 차이를 '수정됨' 으로 보면 안 된다.
_DESCRIPTIVE_SCOPE_KEYS = {"industry_name", "source_name", "guard"}

def decision_payload(req: QualificationRequirement)->dict:
    scope={k:v for k,v in (req.scope or {}).items() if k not in _DESCRIPTIVE_SCOPE_KEYS and k!="guard_basis"}
    payload={"type":req.type,"operator":req.operator,"value":req.value,"unit":req.unit,"period_months":req.period_months,"scope":scope,"required":req.required,"requirement_role":req.requirement_role,"condition_complexity":req.condition_complexity,"group_operator":req.group_operator}
    # 가드 평가를 거친 요건(scope.guard=assessed)은 판정이 원문을 다시 읽지 않는다. 그런 요건은 원문이 달라도 판정이
    # 같으므로 원문을 비교하지 않는다 — 한 조항의 지역만 바꿨는데 같은 조항의 업종이 '수정' 으로 잡혔다(가상 변경 시험).
    if (req.scope or {}).get("guard")!="assessed":
        payload["raw"]=_norm_text(req.raw)
    return payload

def _pair_same_anchor(
    baseline: list[QualificationRequirement], current: list[QualificationRequirement]
) -> list[tuple[QualificationRequirement, QualificationRequirement]]:
    pairs = []
    rest_b = list(baseline)
    rest_c = list(current)
    for b in list(rest_b):
        same = next((c for c in rest_c if decision_payload(c) == decision_payload(b)), None)
        if same is not None:
            pairs.append((b, same)); rest_b.remove(b); rest_c.remove(same)
    order = lambda r: (str(r.group_operator), str(r.value), r.requirement_key)  # noqa: E731
    pairs.extend(zip(sorted(rest_b, key=order), sorted(rest_c, key=order)))
    return pairs


def diff_requirements(baseline:list[QualificationRequirement], current:list[QualificationRequirement])->list[RequirementChange]:
    baseline_by_key={r.requirement_key:r for r in baseline}; current_by_key={r.requirement_key:r for r in current}
    matched_base:set[str]=set(); matched_current:set[str]=set(); pairs=[]
    base_fallback={}
    for b in baseline:
        if b.requirement_key not in matched_base: base_fallback.setdefault(semantic_identity(b),[]).append(b)
    current_fallback={}
    for c in current:
        if c.requirement_key not in matched_current: current_fallback.setdefault(semantic_identity(c),[]).append(c)
    for identity in sorted(set(base_fallback)&set(current_fallback)):
        # 같은 자리(유형 + 원문 뼈대)의 요건이 여럿일 수 있다 — 한 조항의 대안 묶음(ANY_OF)이
        # 그렇다. 예전에는 하나씩일 때만 짝지어 나머지가 추출 순서 키로 떨어졌다. 판정 내용이
        # 같은 것끼리 먼저(UNCHANGED), 남은 것은 값 순서대로(MODIFIED) 짝짓는다.
        for b,c in _pair_same_anchor(base_fallback[identity],current_fallback[identity]):
            pairs.append((b,c,f"semantic:{identity}")); matched_base.add(b.requirement_key); matched_current.add(c.requirement_key)
    for key in sorted(set(baseline_by_key)&set(current_by_key)):
        if key in matched_base or key in matched_current:
            continue
        b,c=baseline_by_key[key],current_by_key[key]
        if b.type==c.type:
            pairs.append((b,c,f"key:{key}")); matched_base.add(key); matched_current.add(key)
    # 원문이 바뀌어 자리(원문 뼈대)로 짝을 못 찾은 요건끼리, 판정 내용이 같으면 같은 요건이다 — 앞에 조항이 끼어
    # 조항 원문이 바뀌자 같은 품명번호 요건이 '삭제 + 추가' 로 잡혔다(가상 변경 시험).
    rest_c=[c for c in current if c.requirement_key not in matched_current]
    for b in baseline:
        if b.requirement_key in matched_base: continue
        same=next((c for c in rest_c if decision_payload(c)==decision_payload(b)),None)
        if same is not None:
            pairs.append((b,same,f"value:{b.type}:{b.value}")); matched_base.add(b.requirement_key); matched_current.add(same.requirement_key); rest_c.remove(same)
    changes=[]
    for b,c,identity in pairs:
        changes.append(RequirementChange(change_type="UNCHANGED" if decision_payload(b)==decision_payload(c) else "MODIFIED",identity=identity,baseline_key=b.requirement_key,current_key=c.requirement_key,baseline=b,current=c))
    for b in baseline:
        if b.requirement_key not in matched_base: changes.append(RequirementChange(change_type="REMOVED",identity=f"removed:{semantic_identity(b)}",baseline_key=b.requirement_key,baseline=b))
    for c in current:
        if c.requirement_key not in matched_current: changes.append(RequirementChange(change_type="ADDED",identity=f"added:{semantic_identity(c)}",current_key=c.requirement_key,current=c))
    order={"MODIFIED":0,"ADDED":1,"REMOVED":2,"UNCHANGED":3}
    return sorted(changes,key=lambda x:(order[x.change_type],x.current_key or x.baseline_key or x.identity))

def requirements_to_revalidate(changes:list[RequirementChange])->list[str]:
    return [item.current_key for item in changes if item.change_type in {"MODIFIED","ADDED"} and item.current_key is not None]


def documents_fingerprint(document_hashes: list[str | None]) -> str | None:
    """한 차수의 문서 지문. 추출 문서 해시를 문서 순서대로 이은 것이다. 해시가 하나라도 없으면 None(비교 불가)."""
    if not document_hashes or any(not item for item in document_hashes):
        return None
    return "|".join(str(item) for item in document_hashes)


def diff_same_documents(baseline: list[QualificationRequirement], current: list[QualificationRequirement]) -> list[RequirementChange]:
    """두 차수의 문서가 같을 때의 차수 비교: 자격 변경은 없다.

    변경공고의 상당수는 일정·공고번호만 바뀌고 문서는 그대로다(2026-10-06 최근 30일 변경공고 12쌍 중 8쌍).
    문서가 같은데 요건이 다르게 나왔다면 그것은 분석의 흔들림이지 공고의 변경이 아니다. 짝이 맞는 요건은
    UNCHANGED 로 잇고, 짝이 없는 현재 요건도 UNCHANGED(기준 없음, 새로 판정)로 둔다. 기준에만 있는 요건은
    삭제로 내보내지 않는다.
    """
    out: list[RequirementChange] = []
    for change in diff_requirements(baseline, current):
        if change.change_type == "REMOVED":
            continue
        if change.change_type != "UNCHANGED":
            change = change.model_copy(update={"change_type": "UNCHANGED"})
        out.append(change)
    return out
