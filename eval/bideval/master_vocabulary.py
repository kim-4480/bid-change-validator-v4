"""업종 마스터 CSV로 IndustryNameResolver를 구현한다 (eval·실험용).

제품(API)은 같은 인터페이스를 DB 기준정보 테이블로 구현한다. 엔진은 어느 쪽인지 모른다.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parents[2] / "data" / "master" / "industry_codes.csv"
_IGNORED = re.compile(r"[\s·ㆍ․,，./\-]+")


def normalize_name(name: str) -> str:
    return _IGNORED.sub("", name or "").casefold()


class CsvIndustryNameResolver:
    def __init__(self, path: Path = DEFAULT_CSV, *, active_only: bool = True) -> None:
        self._by_name = _load(str(path), active_only)

    def code_for(self, name: str) -> str | None:
        return self._by_name.get(normalize_name(name))


@lru_cache(maxsize=4)
def _load(path: str, active_only: bool) -> dict[str, str]:
    by_name: dict[str, str] = {}
    ambiguous: set[str] = set()
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if active_only and row.get("active") not in {"Y", "true", "True", "1"}:
                continue
            key = normalize_name(row["name"])
            if key in by_name and by_name[key] != row["code"]:
                ambiguous.add(key)
            by_name.setdefault(key, row["code"])
    # 같은 이름이 여러 코드를 가리키면 추측하지 않는다.
    for key in ambiguous:
        by_name.pop(key, None)
    return by_name
