import json

from bideval.notice_sample import load_sample


def test_load_sample_reads_versions_and_changed_pairs(tmp_path):
    for directory in ("N1-000", "C1-000", "C1-001"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "a.blocks.json").write_text(json.dumps([{"block_index": 0, "text": "3. 입찰참가자격"}]))
    doc = [{"name": "입찰공고문.pdf", "blocks": "a.blocks.json"}]
    (tmp_path / "manifest.json").write_text(json.dumps({
        "notices": [{"notice_no": "N1", "dir": "N1-000", "documents": doc}],
        "changed": [{"notice_no": "C1", "versions": [{"order": "000", "dir": "C1-000", "documents": doc},
                                                     {"order": "001", "dir": "C1-001", "documents": doc}]}],
    }))
    notices, changed = load_sample(tmp_path)
    assert [n.label for n in notices] == ["N1-000"]
    assert [[v.label for v in c] for c in changed] == [["C1-000", "C1-001"]]
    assert notices[0].documents[0].blocks[0]["text"] == "3. 입찰참가자격"
