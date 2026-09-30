"""PR 변경 파일을 영역별로 묶고, 두 영역 이상이면 실패한다.

`cross-zone` 라벨이 붙은 PR은 경고만 남긴다. 영역 정의는 ADR 0001과 CODEOWNERS를 따른다.
"""
from __future__ import annotations

import os
import sys

# (경로 접두사, 영역). 먼저 일치하는 규칙이 이긴다. None은 어느 영역에도 속하지 않는 공용 파일.
ZONES: list[tuple[str, str | None]] = [
    ("apps/web/", "web"),
    ("apps/api/", "api"),
    ("docker-compose", "api"),
    ("engine/", "llm"),
    ("eval/", "llm"),
    ("contracts/", "contracts"),
    ("db/", "db"),
    ("data/", "db"),
    ("infra/", "infra"),
    (".github/", "infra"),
    ("docs/", None),
    ("", None),
]


def zone_of(path: str) -> str | None:
    for prefix, zone in ZONES:
        if path.startswith(prefix):
            return zone
    return None


def main(changed_file: str) -> int:
    paths = [line.strip() for line in open(changed_file, encoding="utf-8") if line.strip()]
    by_zone: dict[str, list[str]] = {}
    for path in paths:
        zone = zone_of(path)
        if zone:
            by_zone.setdefault(zone, []).append(path)
    for zone, files in sorted(by_zone.items()):
        print(f"[{zone}] {len(files)} files")
        for f in files[:10]:
            print(f"  {f}")
    if len(by_zone) <= 1:
        print("OK: 단일 영역 PR")
        return 0
    message = f"영역 {len(by_zone)}개를 동시에 변경: {', '.join(sorted(by_zone))}"
    if os.environ.get("ALLOW_CROSS_ZONE") == "true":
        print(f"::warning::{message} (cross-zone 라벨로 허용)")
        return 0
    print(f"::error::{message}. 계약 PR과 영역별 구현 PR로 나누거나, 합의 후 cross-zone 라벨을 붙이세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
