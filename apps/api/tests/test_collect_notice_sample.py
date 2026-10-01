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
    keys: list[str] = []

    def __init__(self, service_key, *_args):
        FakeClient.keys.append(service_key)

    def fetch_page(self, *, business_type, inquiry_type, page_number, page_size, bid_notice_no=None, **_):
        name = inquiry_type.name
        if name == "REGISTERED":
            items = [_item("R1", "000"), _item("R2", "000", docs=False), _item("R3", "000")]
            items[0]["stdNtceDocUrl"] = "https://example.test/R1-std"  # 확장자 없는 표준공고문
        elif name == "CHANGED":
            items = [_item("C2", "000"), _item("C1", "001")]
        elif bid_notice_no == "C2":  # 차수가 하나뿐인 변경공고
            items = [_item("C2", "000")]
        else:  # NOTICE_NUMBER — 모든 차수
            items = [_item(bid_notice_no, "000"), _item(bid_notice_no, "001")]
        return SimpleNamespace(items=items, total_count=len(items), page_size=page_size)


def test_collector_writes_blocks_and_manifest(tmp_path, monkeypatch):
    downloaded = []

    def fake_download(_session, url):
        downloaded.append(url)
        return b"%PDF fake " + url.encode()

    filenames = []

    def fake_extract(source, *, filename, content_type):
        filenames.append(filename)
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
    assert "표준공고문" in filenames                                              # 확장자를 꾸며 붙이지 않는다
    assert any(d["name"] == "표준공고문" for d in manifest["notices"][0]["documents"])
    unselected = {(u["notice_no"], u["kind"], u["reason"]): u["versions"] for u in manifest["unselected"]}
    assert set(unselected) == {("R2", "registered", "no_documents"), ("C2", "changed", "single_version")}
    assert unselected[("R2", "registered", "no_documents")] == [{"order": "000", "dir": None, "documents": []}]
    kept = unselected[("C2", "changed", "single_version")][0]                   # 기준 밖 후보도 추출 결과를 남긴다
    assert (tmp_path / kept["dir"] / kept["documents"][0]["blocks"]).is_file()
    referenced = {n["dir"] for n in manifest["notices"]} | {v["dir"] for c in manifest["changed"] for v in c["versions"]}
    referenced |= {v["dir"] for versions in unselected.values() for v in versions if v["dir"]}
    on_disk = {p.name for p in tmp_path.iterdir() if p.is_dir()}
    assert on_disk == referenced                                                # manifest 에 없는 디렉터리는 없다
    assert "R2-000" not in on_disk


def test_percent_encoded_key_is_decoded_once(monkeypatch, tmp_path):
    """공공데이터포털 키는 퍼센트 인코딩돼 있다. 그대로 넘기면 requests 가 다시 인코딩해 인증이 실패한다."""
    monkeypatch.chdir(tmp_path)  # 저장소 .env 를 읽지 않게
    monkeypatch.setenv("G2B_SERVICE_KEY", "abc%2Bdef%3D%3D")
    assert collector._service_key() == "abc+def=="


def test_missing_key_stops_with_a_message(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("G2B_SERVICE_KEY", raising=False)
    import pytest
    with pytest.raises(SystemExit, match="G2B_SERVICE_KEY"):
        collector._service_key()
