"""나라장터 최근 공고를 받아 추출 비교용 표본(텍스트 블록)을 만든다. **국내 네트워크에서** 돌린다.

공공데이터포털·나라장터는 해외 IP 접속을 끊는 경우가 있어 클라우드 세션에서 직접 받을 수 없다
(2026-10-01 확인). 이 스크립트를 로컬에서 돌려 결과 디렉터리를 커밋하면, 비교 러너
(live_extraction_probe.py --sample, diff_probe.py --sample)가 그것을 읽는다.

    # 저장소 루트에서, apps/api 의존성이 설치된 환경으로. 키는 환경변수 또는 .env 의
    # G2B_SERVICE_KEY 를 읽는다(퍼센트 인코딩된 키도 그대로 두면 된다).
    PYTHONPATH=$PWD python eval/experiments/collect_notice_sample.py \
        --days 7 --notices 12 --changed 6 --out eval/golden/notice-sample-20261001

받는 것
  - 등록공고: 업무 종류별 최근 공고 중 공고문(HWP/HWPX/PDF/DOCX)이 추출되는 것 --notices 건.
  - 변경공고: 최근 변경된 공고 --changed 건의 **모든 차수**. 차수 쌍으로 차수 비교(S4)를 잰다.

남기는 것은 추출한 텍스트 블록(JSON)과 출처 정보뿐이다. 원본 파일은 저장하지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from apps.api.app.config import Settings
from apps.api.app.schemas import BusinessType, NoticeInquiryType
from apps.api.app.services.document_extraction import extract_document
from apps.api.app.services.g2b import KST, G2BClient
from apps.api.app.services.notices import _documents

BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
EXTRACTABLE = re.compile(r"\.(hwp|hwpx|pdf|docx)$", re.IGNORECASE)
# 표준공고문 외에 자격 조항이 흔히 들어 있는 첨부. 나머지(서식·도면·내역서)는 받지 않는다.
RELEVANT_NAME = re.compile(r"공고|제안요청|과업|규격|설명서|지시서|유의서")
MAX_BYTES = 30 * 1024 * 1024


def _service_key() -> str:
    """앱과 같은 방식으로 키를 읽는다 — 환경변수가 없으면 저장소 루트의 .env, 퍼센트 인코딩은 푼다.

    공공데이터포털이 주는 키는 퍼센트 인코딩된 형태라 .env 에도 그렇게 들어 있다. 그대로 requests
    params 에 넣으면 '%' 가 '%25' 로 다시 인코딩돼 인증이 실패한다(앱은 config.decoded_g2b_service_key
    로 풀어 쓴다). 데스크톱 세션 점검에서 찾았다(2026-10-01).
    """
    key = Settings().decoded_g2b_service_key
    if not key:
        raise SystemExit("G2B_SERVICE_KEY 가 없습니다. 환경변수나 저장소 루트의 .env 에 넣어 주세요.")
    return key


def _download(session: requests.Session, url: str) -> bytes:
    with session.get(url, stream=True, timeout=60, allow_redirects=True,
                     headers={"User-Agent": "bid-change-validator/0.1"}) as response:
        response.raise_for_status()
        data = io.BytesIO()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            data.write(chunk)
            if data.tell() > MAX_BYTES:
                raise ValueError("file too large")
        return data.getvalue()


def _version_documents(session: requests.Session, item: dict[str, Any]) -> list[dict[str, Any]]:
    """한 차수의 관련 문서를 받아 추출한다. 파일은 쓰지 않는다 — 채택된 차수만 _write_version 이 쓴다."""
    saved = []
    for doc in _documents(item):
        name = doc["name"]
        if doc["source_field"] != "stdNtceDocUrl" and not (EXTRACTABLE.search(name) and RELEVANT_NAME.search(name)):
            continue
        try:
            payload = _download(session, doc["url"])
            # 표준공고문은 확장자 없이 온다. 이름을 그대로 넘겨 형식을 내용(매직바이트)으로 가리게 한다 —
            # ".pdf" 를 붙이면 HWP·HWPX 표준공고문이 PDF 로 읽혀 전부 실패했다(데스크톱 수집 54/54).
            result = extract_document(io.BytesIO(payload), filename=name, content_type=None)
        except Exception as error:  # noqa: BLE001 - 한 문서 실패가 표본 전체를 멈추면 안 된다
            print(f"    skip {name}: {type(error).__name__}", file=sys.stderr)
            continue
        if not result.blocks:
            continue
        digest = hashlib.sha256(payload).hexdigest()
        saved.append({
            "name": name,
            "document_order": doc["document_order"],
            "extractor": result.extractor,
            "source_url": doc["url"],
            "source_file_sha256": digest,
            "blocks": f"{digest[:16]}.blocks.json",
            "_blocks": result.blocks,
        })
    return saved


def _write_version(out: Path, directory: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """채택된 차수의 블록 파일을 쓰고 manifest 용 문서 목록을 돌려준다. 탈락 후보는 디스크에 남지 않는다."""
    version_dir = out / directory
    version_dir.mkdir(exist_ok=True)
    listed = []
    for doc in documents:
        (version_dir / doc["blocks"]).write_text(json.dumps(doc["_blocks"], ensure_ascii=False), encoding="utf-8")
        listed.append({key: value for key, value in doc.items() if key != "_blocks"})
    return listed


def _has_notice_document(documents: list[dict[str, Any]]) -> bool:
    return any("공고" in d["name"] for d in documents)


def _items(client: G2BClient, business_type: BusinessType, inquiry: NoticeInquiryType, start, end, limit) -> list[dict]:
    items: list[dict] = []
    page_number = 1
    while len(items) < limit * 4:
        page = client.fetch_page(business_type=business_type, inquiry_type=inquiry, page_number=page_number,
                                 page_size=100, window_started_at=start, window_ended_at=end)
        items.extend(page.items)
        if page_number * page.page_size >= page.total_count or not page.items:
            break
        page_number += 1
    return items


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--notices", type=int, default=12, help="등록공고 표본 수")
    parser.add_argument("--changed", type=int, default=6, help="변경공고(모든 차수) 표본 수")
    parser.add_argument("--business-types", nargs="*", default=["SERVICE", "GOODS", "CONSTRUCTION"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    client = G2BClient(_service_key(), BASE_URL)
    session = requests.Session()
    end = datetime.now(KST)
    start = end - timedelta(days=args.days)
    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {"collected_at": end.isoformat(), "window_days": args.days, "notices": [], "changed": []}
    types = [BusinessType[name] for name in args.business_types]

    # 등록공고 — 업무 종류를 돌아가며 고른다.
    per_type = max(1, -(-args.notices // len(types)))
    for business_type in types:
        taken = 0
        for item in _items(client, business_type, NoticeInquiryType.REGISTERED, start, end, per_type):
            if taken >= per_type or len(manifest["notices"]) >= args.notices:
                break
            notice_no, order = item.get("bidNtceNo"), item.get("bidNtceOrd") or "000"
            print(f"[{business_type.name}] 탐색 {notice_no}-{order} {item.get('bidNtceNm', '')[:40]}")
            documents = _version_documents(session, item)
            if not _has_notice_document(documents):
                continue
            directory = f"{notice_no}-{order}"
            manifest["notices"].append({"notice_no": notice_no, "order": order, "business_type": business_type.name,
                                        "title": item.get("bidNtceNm"), "dir": directory,
                                        "documents": _write_version(args.out, directory, documents)})
            taken += 1
            time.sleep(0.5)

    # 변경공고 — 공고번호로 모든 차수를 다시 받아 차수별 문서를 남긴다.
    for business_type in types:
        for item in _items(client, business_type, NoticeInquiryType.CHANGED, start, end, args.changed):
            if len(manifest["changed"]) >= args.changed:
                break
            notice_no = item.get("bidNtceNo")
            if any(c["notice_no"] == notice_no for c in manifest["changed"]):
                continue
            history = client.fetch_page(business_type=business_type, inquiry_type=NoticeInquiryType.NOTICE_NUMBER,
                                        page_number=1, page_size=50, bid_notice_no=notice_no).items
            versions = []
            for version in sorted(history, key=lambda v: v.get("bidNtceOrd") or ""):
                order = version.get("bidNtceOrd") or "000"
                documents = _version_documents(session, version)
                if _has_notice_document(documents):
                    versions.append({"order": order, "dir": f"{notice_no}-{order}", "documents": documents})
            if len(versions) >= 2:
                print(f"[CHANGED {business_type.name}] {notice_no} 차수 {[v['order'] for v in versions]}")
                for version in versions:
                    version["documents"] = _write_version(args.out, version["dir"], version["documents"])
                manifest["changed"].append({"notice_no": notice_no, "business_type": business_type.name,
                                            "title": item.get("bidNtceNm"), "versions": versions})
            time.sleep(0.5)

    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"등록공고 {len(manifest['notices'])}건, 변경공고 {len(manifest['changed'])}건 → {args.out}")


if __name__ == "__main__":
    main()
