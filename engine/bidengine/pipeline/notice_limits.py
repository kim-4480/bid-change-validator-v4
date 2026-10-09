"""나라장터가 구조화해 둔 참가 제한(면허제한·참가가능지역)을 문서에서 뽑은 요건과 맞춘다(2026-10-10).

공고 문서를 읽는 것과 무관한 두 번째 근거다. 발주처가 나라장터에 직접 입력한 값이라 코드로 온다.

    면허제한   [{"group": "1", "name": "건설폐기물 중간처리업", "code": "1253"}, …]
               묶음(group)끼리는 대안이고, 한 묶음 안의 면허는 모두 필요하다.
    참가가능지역 ["대전광역시"] — 여럿이면 그중 한 곳.

발주처가 비워 두는 공고가 있어(표본에서 업종 요건이 있는 공고의 15%) 문서 읽기를 대신하지 못한다. 그래서 고치는 것은 셋뿐이다.

  1. 문서 요건이 같은 말을 하고 있지 않으면 요건으로 더한다. 맞으면 충족, 안 맞으면 확인 필요다 — 부적합의 근거로는 쓰지 않는다.
     상위 면허가 대신하는 경우(토목건축공사업 ⊃ 건축공사업)와 공동수급으로 채우는 경우를 엔진이 가를 수 없어서다.
  2. 문서에서 추론으로 얻은 업종코드(묶음 이름에서 푼 코드)가 면허제한에 없으면 버린다. 추론보다 입력된 값이 앞선다.
  3. 문서는 필수라고 읽었는데 면허제한에서는 대안인 업종코드는, 안 맞아도 확인 필요로 낸다.

문서와 면허제한이 같은 값을 말하면 아무것도 바꾸지 않는다 — 그 요건은 지금처럼 부적합의 근거가 된다.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from bidengine.contracts import QualificationRequirement
from bidengine.normalization.regions import sidos_of

# 판정기가 '안 맞아도 부적합으로 확정하지 않는' 근거 표시(scope["evidence"]).
EVIDENCE_NOTICE_API = "notice_api"
EVIDENCE_API_CONFLICT = "api_conflict"
_CODE_RE = re.compile(r"[0-9]{4}")
_NO_LIMIT = ("전국", "제한없음", "해당없음")


class NoticeLicense(BaseModel):
    group: str = "1"
    name: str = ""
    code: str | None = None


class NoticeLimits(BaseModel):
    """공고 API 의 구조화된 참가 제한. 비어 있으면 '제한 없음' 이 아니라 '입력되지 않음' 이다."""

    licenses: list[NoticeLicense] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)

    @classmethod
    def from_collected(cls, data: dict[str, Any] | None) -> "NoticeLimits":
        data = data or {}
        return cls(
            licenses=[NoticeLicense(group=str(item.get("group") or "1"), name=str(item.get("name") or ""), code=item.get("code"))
                      for item in data.get("licenses") or []],
            regions=[str(region) for region in data.get("regions") or []],
        )


def license_groups(limits: NoticeLimits) -> list[set[str]]:
    """묶음별 업종코드. 코드 없는 면허는 뺀다."""
    groups: dict[str, set[str]] = {}
    for item in limits.licenses:
        if item.code and _CODE_RE.fullmatch(item.code):
            groups.setdefault(item.group, set()).add(item.code)
    return [codes for _group, codes in sorted(groups.items())]


def _same_as_documents(requirements: list[QualificationRequirement], groups: list[set[str]]) -> bool:
    """문서에서 뽑은 업종 요건이 면허제한과 같은 구조인가. 같으면 면허제한을 따로 더하지 않는다.

    묶음이 하나면 그 코드들이 모두 문서의 필수 업종이어야 하고, 한 코드짜리 묶음 여럿이면 문서의 한 대안 묶음과 같아야 한다.
    """
    industry = [r for r in requirements if r.type == "INDUSTRY" and r.requirement_role == "mandatory"]
    required = {str(r.value) for r in industry if (r.group_operator or "ALL_OF") == "ALL_OF"}
    if len(groups) == 1:
        return groups[0] <= required
    if all(len(group) == 1 for group in groups):
        wanted = set().union(*groups)
        alternatives: dict[str, set[str]] = {}
        for r in industry:
            if r.group_operator == "ANY_OF" and r.requirement_group_key:
                alternatives.setdefault(r.requirement_group_key, set()).add(str(r.value))
        return any(codes == wanted for codes in alternatives.values())
    return False


def merge_notice_limits(
    requirements: list[QualificationRequirement], limits: NoticeLimits | None, *, notice_version_id: str,
) -> tuple[list[QualificationRequirement], list[dict[str, Any]]]:
    """(요건, 진단). 진단은 파이프라인의 다른 진단과 같은 모양이다."""
    if limits is None or (not limits.licenses and not limits.regions):
        return requirements, []
    diagnostics: list[dict[str, Any]] = []
    out = list(requirements)
    names = {item.code: item.name for item in limits.licenses if item.code}
    groups = license_groups(limits)

    if groups:
        api_codes = set().union(*groups)
        common = set.intersection(*groups)
        # 2. 추론으로 얻은 코드가 면허제한에 없으면 버린다.
        kept = []
        for item in out:
            inferred = item.type == "INDUSTRY" and item.scope.get("evidence") == "family"
            if inferred and str(item.value) not in api_codes:
                diagnostics.append({"code": "CLAUSE_NOT_LABELLED", "raw": item.raw, "reason": "INFERRED_CODE_NOT_IN_NOTICE_LIMITS"})
            else:
                kept.append(item)
        out = kept
        # 3. 문서는 필수, 면허제한은 대안.
        out = [
            item.model_copy(update={"scope": {**item.scope, "evidence": EVIDENCE_API_CONFLICT}})
            if item.type == "INDUSTRY" and (item.group_operator or "ALL_OF") == "ALL_OF"
            and str(item.value) in api_codes and str(item.value) not in common else item
            for item in out
        ]
        # 1. 문서 요건이 면허제한과 같은 말을 하고 있지 않으면, 면허제한을 그대로 요건으로 더한다.
        #    묶음 하나가 요건 하나다("이 면허들을 모두 보유" — scope.with_codes). 묶음이 여럿이면 서로 대안이다.
        if not _same_as_documents(out, groups):
            described = " 또는 ".join(
                "(" + ", ".join(f"{names.get(code, '')}/{code}" for code in sorted(group)) + ")" for group in groups
            )
            many = len(groups) > 1
            for index, group in enumerate(groups, start=1):
                first, *others = sorted(group)
                out.append(QualificationRequirement(
                    requirement_key=f"NOTICE-LIMIT-INDUSTRY-{index:02d}", notice_version_id=notice_version_id, type="INDUSTRY",
                    operator="MATCH", value=first, raw=f"나라장터 면허제한: {described}",
                    requirement_group_key="NOTICE-LIMIT-INDUSTRY", group_operator="ANY_OF" if many else "ALL_OF",
                    scope={"origin": "NOTICE_API", "industry_name": names.get(first, ""), "with_codes": others,
                           "evidence": EVIDENCE_NOTICE_API, "guard": "assessed"},
                ))

    regions = [region for region in limits.regions if region and not any(token in region.replace(" ", "") for token in _NO_LIMIT)]
    if regions:
        api_sidos = set().union(*(sidos_of(region) for region in regions))
        doc_sidos = set().union(set(), *(sidos_of(item.value) for item in out if item.type == "REGION"))
        if api_sidos and not (api_sidos & doc_sidos):
            raw = "나라장터 참가가능지역: " + ", ".join(regions)
            many = len(regions) > 1
            for index, region in enumerate(regions, start=1):
                out.append(QualificationRequirement(
                    requirement_key=f"NOTICE-LIMIT-REGION-{index:02d}", notice_version_id=notice_version_id, type="REGION",
                    operator="MATCH", value=region, raw=raw,
                    requirement_group_key="NOTICE-LIMIT-REGION", group_operator="ANY_OF" if many else "ALL_OF",
                    scope={"origin": "NOTICE_API", "evidence": EVIDENCE_NOTICE_API, "guard": "assessed"},
                ))
    return out, diagnostics
