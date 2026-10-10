"""나라장터가 구조화해 둔 참가 제한(면허제한·참가가능지역)을 공고 차수에 받아 두고 분석에 넘긴다.

공고 목록 조회에는 "업종 제한 있음" 표시만 있고 값은 두 조회에 따로 있다. 분석을 처음 돌릴 때 한 번 받아
`bid_notice_versions.participation_limits` 에 둔다 — 다시 분석해도 같은 입력을 본다.

    NULL                                  아직 받지 않음
    {"licenses": [], "regions": []}       받았는데 발주처가 입력한 제한이 없음
    {"licenses": [{"group": "1", "name": "건축공사업", "code": "0002"}], "regions": ["대전광역시"]}

조회가 실패하면 저장하지 않고 None 을 돌려준다. 분석은 문서만으로 진행하고, 다음 분석에서 다시 받는다.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy.orm import Session

from bidengine.contracts import QualificationRequirement
from bidengine.pipeline.notice_limits import NoticeLimits

from ..config import Settings
from ..models import BidNoticeVersion
from .g2b import G2BApiError, G2BClient

# (공고번호, 차수) → {"licenses": [...], "regions": [...]} 조회 원본
LimitsFetcher = Callable[[str, str], dict[str, list[dict[str, Any]]]]

_NAME_CODE_RE = re.compile(r"^(.*?)/(\d{4})$")
# 공고 목록 조회 원본(raw_json)에서 엔진이 '제한 없는 입찰' 인지 볼 때 쓰는 값.
_FLAG_KEYS = ("cntrctCnclsMthdNm", "indstrytyLmtYn", "prdctClsfcLmtYn", "bidPrtcptLmtYn")


def normalize_participation_limits(raw: dict[str, Iterable[dict[str, Any]]]) -> dict[str, Any]:
    """조회 원본을 저장 모양으로. 면허제한명은 "건축공사업/0002" 처럼 이름과 코드가 붙어 온다."""
    licenses = []
    for item in raw.get("licenses") or []:
        text = str(item.get("lcnsLmtNm") or "").strip()
        if not text:
            continue
        match = _NAME_CODE_RE.match(text)
        licenses.append({
            "group": str(item.get("lmtGrpNo") or "1"),
            "name": match.group(1).strip() if match else text,
            "code": match.group(2) if match else None,
        })
    regions = [
        str(item.get("prtcptPsblRgnNm") or "").strip()
        for item in raw.get("regions") or []
        if str(item.get("prtcptPsblRgnNm") or "").strip()
    ]
    return {"licenses": licenses, "regions": regions}


def ensure_participation_limits(
    db: Session, version: BidNoticeVersion, fetch: LimitsFetcher | None,
) -> dict[str, Any] | None:
    """저장된 값이 있으면 그것을, 없고 fetch 가 있으면 받아서 저장하고 돌려준다. 실패하면 None."""
    if version.participation_limits is not None:
        return version.participation_limits
    if fetch is None:
        return None
    try:
        raw = fetch(version.notice.bid_notice_no, version.bid_notice_order)
    except G2BApiError:
        return None
    version.participation_limits = normalize_participation_limits(raw)
    db.flush()
    return version.participation_limits


def engine_notice_limits(version: BidNoticeVersion, value: dict[str, Any] | None) -> NoticeLimits | None:
    """엔진에 넘길 모양. 받은 값이 없으면 None — 엔진은 문서만으로 분석한다."""
    if value is None:
        return None
    raw = version.raw_json if isinstance(version.raw_json, dict) else {}
    flags = {key: raw[key] for key in _FLAG_KEYS if raw.get(key) not in (None, "")}
    return NoticeLimits.from_collected({**value, "flags": flags})


def participation_limits_fetcher(settings: Settings) -> LimitsFetcher | None:
    """설정으로 만든 조회 함수. 나라장터 키가 없거나 조회를 꺼 두었으면 None(분석은 문서만으로 진행한다)."""
    service_key = settings.decoded_g2b_service_key
    if service_key is None or not settings.participation_limits_lookup_enabled:
        return None
    client = G2BClient(
        service_key=service_key, base_url=settings.g2b_base_url,
        timeout_seconds=settings.g2b_request_timeout_seconds,
    )
    return lambda bid_notice_no, bid_notice_order: client.fetch_participation_limits(
        bid_notice_no=bid_notice_no, bid_notice_order=bid_notice_order,
    )


def notice_api_grounded_keys(
    requirements: Iterable[QualificationRequirement], value: dict[str, Any] | None,
) -> set[str]:
    """나라장터에서 온 요건 가운데, 저장된 참가 제한에 그 값이 지금도 있는 것의 키.

    문서에서 뽑은 요건은 인용문이 현재 문서에 있는지로 근거를 확인한다. 나라장터에서 온 요건은 인용할 문서가 없으므로
    저장된 조회 값에 그 업종코드·지역이 있는지로 확인한다. 값이 없거나 달라졌으면 근거가 없는 요건이다.
    """
    if not value:
        return set()
    codes = {str(item.get("code")) for item in value.get("licenses") or [] if item.get("code")}
    regions = {str(region) for region in value.get("regions") or []}
    grounded: set[str] = set()
    for requirement in requirements:
        if requirement.scope.get("origin") != "NOTICE_API":
            continue
        if requirement.type == "INDUSTRY":
            wanted = {str(requirement.value), *[str(code) for code in requirement.scope.get("with_codes") or []]}
            if wanted <= codes:
                grounded.add(requirement.requirement_key)
        elif requirement.type == "REGION" and str(requirement.value) in regions:
            grounded.add(requirement.requirement_key)
    return grounded
