"""기관 주소(data/master/institution_codes.csv)에서 시·군·구 이름 사전을 만든다.

    python engine/scripts/build_region_vocab.py > engine/bidengine/normalization/region_vocab.py

지역은 닫힌 어휘다. 공고의 지역 요건을 낱말 꼴(…시·…군·…구)로 짐작하지 않고 사전에 있는 이름으로만 읽는다.
"의북구" 처럼 조사가 붙은 낱말이나 "국내에 본사와 생산공장" 같은 문장은 사전에 없으므로 지역이 되지 않는다.
엔진은 DB 를 보지 않으므로 사전을 파이썬 모듈로 만들어 함께 배포한다.
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

SIDO = (
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", "울산광역시", "세종특별자치시",
    "경기도", "강원특별자치도", "강원도", "충청북도", "충청남도", "전북특별자치도", "전라북도", "전라남도", "경상북도",
    "경상남도", "제주특별자치도", "전남광주통합특별시",
)
SIGUNGU_RE = re.compile(r"[가-힣]{1,5}(?:시|군|구)")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    csv.field_size_limit(10**9)
    parents: dict[str, set[str]] = defaultdict(set)
    with (root / "data/master/institution_codes.csv").open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            address = (json.loads(row["raw_json"]).get("adrs") or "").split()
            if len(address) >= 2 and address[0] in SIDO and SIGUNGU_RE.fullmatch(address[1]):
                parents[address[1]].add(address[0])
    out = sys.stdout
    out.write('"""시·군·구 이름 사전. engine/scripts/build_region_vocab.py 가 기관 주소에서 만든다 — 손으로 고치지 않는다."""\n\n')
    out.write("# 시·군·구 이름 -> 그 이름이 쓰이는 시·도들(같은 이름이 여러 시·도에 있다: 중구·북구·동구 …)\n")
    out.write("SIGUNGU_PARENTS: dict[str, frozenset[str]] = {\n")
    for name in sorted(parents):
        out.write(f"    {name!r}: frozenset({sorted(parents[name])!r}),\n")
    out.write("}\n")


if __name__ == "__main__":
    main()
