"""collect_notice_sample.py 가 만든 표본 디렉터리를 읽는다."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SampleDocument:
    name: str
    document_key: str
    blocks: list[dict[str, Any]]


@dataclass
class SampleVersion:
    label: str            # "<공고번호>-<차수>"
    documents: list[SampleDocument]


def _version(root: Path, directory: str, documents: list[dict[str, Any]]) -> SampleVersion:
    docs = [
        SampleDocument(
            name=d["name"],
            document_key=f"{directory}/{d['blocks']}",
            blocks=json.loads((root / directory / d["blocks"]).read_text(encoding="utf-8")),
        )
        for d in documents
    ]
    return SampleVersion(label=directory, documents=docs)


def load_sample(root: Path) -> tuple[list[SampleVersion], list[list[SampleVersion]]]:
    """(등록공고 차수 목록, 변경공고별 차수 목록)."""
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    notices = [_version(root, n["dir"], n["documents"]) for n in manifest.get("notices", [])]
    changed = [
        [_version(root, v["dir"], v["documents"]) for v in c["versions"]]
        for c in manifest.get("changed", [])
    ]
    return notices, changed
