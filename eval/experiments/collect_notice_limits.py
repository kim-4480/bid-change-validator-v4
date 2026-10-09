"""표본 공고마다 나라장터가 구조화해 둔 참가 제한(면허제한·참가가능지역)을 받아 둔다(2026-10-10).

    python eval/experiments/collect_notice_limits.py --sample eval/golden/notice-sample-20261006f

공고 첨부 문서를 읽지 않아도 나라장터 공고 API 가 이미 답하는 것이 있다: 어떤 업종(면허)을 요구하는지, 어느 지역
업체만 참가할 수 있는지. 문장 해석과 무관한 근거라서 문서에서 뽑은 요건을 대조하는 데 쓴다.

공고 폴더마다 notice_api.json 을 쓴다.
  licenses: [{"group": "1", "seq": "1", "name": "건축공사업", "code": "0002", "raw": {...}}]  — 면허제한 조회
  regions:  ["대전광역시"]                                                                   — 참가가능지역 조회
  flags:    {"indstrytyLmtYn": "Y", ...}                                                     — 공고 목록 조회의 제한 표시
조회가 실패한 항목은 errors 에 적는다. 값이 없는 것(제한 없음)과 못 받은 것을 구분하려는 것이다.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from apps.api.app.config import Settings
from apps.api.app.schemas import BusinessType, NoticeInquiryType
from apps.api.app.services.g2b import G2BApiError, G2BClient

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
FLAG_KEYS = ("indstrytyLmtYn", "prdctClsfcLmtYn", "bidPrtcptLmtYn", "cmmnSpldmdCorpRgnLmtYn", "cmmnSpldmdMethdNm",
             "rgnLmtBidLocplcJdgmBssNm", "cntrctCnclsMthdNm", "cnstrtsiteRgnNm")
_NAME_CODE_RE = re.compile(r"^(.*?)/(\d{4})$")


def _sub(client: G2BClient, endpoint: str, notice_no: str, order: str) -> list[dict]:
    items: list[dict] = []
    page_number = 1
    while True:
        page = client._fetch_json_page(endpoint=endpoint, params={
            "serviceKey": client._service_key, "pageNo": page_number, "numOfRows": 100, "type": "json",
            "inqryDiv": "2", "bidNtceNo": notice_no, "bidNtceOrd": order,
        })
        items.extend(page.items)
        if page_number * page.page_size >= page.total_count or not page.items:
            return items
        page_number += 1


def collect(client: G2BClient, notice_no: str, order: str, business_type: str) -> dict:
    out: dict = {"notice_no": notice_no, "order": order, "licenses": [], "regions": [], "flags": {}, "errors": []}
    try:
        for item in _sub(client, "getBidPblancListInfoLicenseLimit", notice_no, order):
            text = str(item.get("lcnsLmtNm") or "").strip()
            match = _NAME_CODE_RE.match(text)
            out["licenses"].append({
                "group": str(item.get("lmtGrpNo") or ""), "seq": str(item.get("lmtSno") or ""),
                "name": match.group(1).strip() if match else text, "code": match.group(2) if match else None, "raw": item,
            })
    except G2BApiError as error:
        out["errors"].append(f"licenses: {error}")
    try:
        out["regions"] = [str(item.get("prtcptPsblRgnNm") or "").strip()
                          for item in _sub(client, "getBidPblancListInfoPrtcptPsblRgn", notice_no, order)
                          if str(item.get("prtcptPsblRgnNm") or "").strip()]
    except G2BApiError as error:
        out["errors"].append(f"regions: {error}")
    try:
        page = client.fetch_page(business_type=BusinessType[business_type], inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
                                 page_number=1, page_size=50, bid_notice_no=notice_no)
        item = next((i for i in page.items if str(i.get("bidNtceOrd") or "") == order), page.items[0] if page.items else {})
        out["flags"] = {key: item[key] for key in FLAG_KEYS if item.get(key) not in (None, "")}
    except (G2BApiError, KeyError) as error:
        out["errors"].append(f"flags: {error}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--force", action="store_true", help="이미 받은 공고도 다시 받는다")
    args = parser.parse_args()

    client = G2BClient(Settings().decoded_g2b_service_key, BASE_URL)
    manifest = json.loads((args.sample / "manifest.json").read_text(encoding="utf-8"))
    done = failed = 0
    for notice in manifest["notices"]:
        target = args.sample / notice["dir"] / "notice_api.json"
        if target.exists() and not args.force:
            continue
        data = collect(client, notice["notice_no"], str(notice["order"]).zfill(3), notice["business_type"])
        target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        done += 1
        failed += bool(data["errors"])
        print(notice["dir"], len(data["licenses"]), data["regions"], data["errors"] or "", flush=True)
        time.sleep(0.2)
    print(f"받음 {done}건, 오류 {failed}건")


if __name__ == "__main__":
    main()
