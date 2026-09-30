"""Canonical Requirement diff for changed-notice revalidation.

Requirement keys are extraction-order based. Match unique semantic identities
before positional keys; only unchanged source conditions may carry answers over.
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

def _norm_text(value: object | None)->str:
    if value is None: return ""
    return re.sub(r"\s+","",str(value).casefold())

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

def decision_payload(req: QualificationRequirement)->dict:
    return {"type":req.type,"operator":req.operator,"value":req.value,"unit":req.unit,"period_months":req.period_months,"scope":req.scope,"required":req.required,"requirement_role":req.requirement_role,"condition_complexity":req.condition_complexity,"group_operator":req.group_operator,"raw":_norm_text(req.raw)}

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
        bs,cs=base_fallback[identity],current_fallback[identity]
        if len(bs)==1 and len(cs)==1:
            b,c=bs[0],cs[0]; pairs.append((b,c,f"semantic:{identity}")); matched_base.add(b.requirement_key); matched_current.add(c.requirement_key)
    for key in sorted(set(baseline_by_key)&set(current_by_key)):
        if key in matched_base or key in matched_current:
            continue
        b,c=baseline_by_key[key],current_by_key[key]
        if b.type==c.type:
            pairs.append((b,c,f"key:{key}")); matched_base.add(key); matched_current.add(key)
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
