"""eval/experiments/collect_notice_sample.py 를 가짜 나라장터 응답으로 끝까지 돌린다.

수집기는 국내 네트워크에서만 실제로 돌릴 수 있어(해외 IP 차단), 흐름은 여기서 검증한다.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("collect_notice_sample", ROOT / "eval/experiments/collect_notice_sample.py")
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def _item(no, order, *, docs=True):
    item = {"bidNtceNo": no, "bidNtceOrd": order, "bidNtceNm": f"{no} 용역"}
    if docs:
        item.update({"ntceSpecDocUrl1": f"https://example.test/{no}-{order}.pdf", "ntceSpecFileNm1": "입찰공고문.pdf",
                     "ntceSpecDocUrl2": f"https://example.test/{no}-{order}-form.hwp", "ntceSpecFileNm2": "서식.hwp"})
    return item


class FakeClient:
    def __init__(self, *_args):
        pass

    def fetch_page(self, *, business_type, inquiry_type, page_number, page_size, bid_notice_no=None, **_):
        name = inquiry_type.name
        if name == "REGISTERED":
            items = [_item("R1", "000"), _item("R2", "000", docs=False), _item("R3", "000")]
        elif name == "CHANGED":
            items = [_item("C1", "001")]
        else:  # NOTICE_NUMBER — 모든 차수
            items = [_item(bid_notice_no, "000"), _item(bid_notice_no, "001")]
        return SimpleNamespace(items=items, total_count=len(items), page_size=page_size)


def test_collector_writes_blocks_and_manifest(tmp_path, monkeypatch):
    downloaded = []

    def fake_download(_session, url):
        downloaded.append(url)
        return b"%PDF fake " + url.encode()

    def fake_extract(source, *, filename, content_type):
        return SimpleNamespace(extractor="FAKE", blocks=[{"block_index": 0, "text": f"3. 입찰참가자격 {filename}"}])

    monkeypatch.setattr(collector, "G2BClient", FakeClient)
    monkeypatch.setattr(collector, "_download", fake_download)
    monkeypatch.setattr(collector, "extract_document", fake_extract)
    monkeypatch.setattr(collector.time, "sleep", lambda _s: None)
    monkeypatch.setenv("G2B_SERVICE_KEY", "test")
    monkeypatch.setattr(sys, "argv", ["collect", "--notices", "2", "--changed", "1", "--business-types", "SERVICE",
                                      "--out", str(tmp_path)])

    collector.main()

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [n["notice_no"] for n in manifest["notices"]] == ["R1", "R3"]          # 문서 없는 R2 는 건너뛴다
    assert [[v["order"] for v in c["versions"]] for c in manifest["changed"]] == [["000", "001"]]
    assert not any(url.endswith("form.hwp") for url in downloaded)              # 서식 첨부는 받지 않는다
    first = manifest["notices"][0]
    blocks = json.loads((tmp_path / first["dir"] / first["documents"][0]["blocks"]).read_text(encoding="utf-8"))
    assert blocks[0]["text"].startswith("3. 입찰참가자격")
    assert not list(tmp_path.rglob("*.pdf"))                                    # 원본은 남기지 않는다
