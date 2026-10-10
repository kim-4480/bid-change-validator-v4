"""PR 변경 파일을 영역별로 묶어 알려 준다. 실패시키지 않는다.

2026-10-08부터 여러 영역을 함께 바꾸는 PR을 막지 않는다. 업무 분담이 영역별로 딱 나뉘어 있지 않고, 겹치는 코드는
PR이 병합된 뒤 각자 pull 받아 맞추는 방식으로 협업하기 때문이다. 리뷰어가 어느 영역을 봐야 하는지 알 수 있게
영역별 변경 파일 수는 계속 출력한다. 영역 정의는 ADR 0001과 CODEOWNERS를 따른다.
"""
from __future__ import annotations

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
        print("단일 영역 PR")
        return 0
    zones = ", ".join(f"{zone} {len(files)}개" for zone, files in sorted(by_zone.items()))
    print(f"::notice::여러 영역을 함께 변경합니다: {zones}. 해당 영역 담당자도 리뷰해 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
