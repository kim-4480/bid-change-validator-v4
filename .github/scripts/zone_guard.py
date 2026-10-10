"""Guard owned source-code zones; only explicitly approved cross-zone PRs pass."""
from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

ZONES: list[tuple[str, str | None]] = [
    ("apps/api/app/copilot/", "llm"),
    ("apps/api/app/document_rag/", "llm"),
    ("apps/web/", "web"),
    ("apps/api/", "api"),
    ("docker-compose", "api"),
    ("engine/", "llm"),
    ("eval/", "llm"),
    ("contracts/", "contracts"),
    ("db/", "db"),
    ("data/", "db"),
    ("deploy/", "infra"),
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


def main(changed_file: str, *, allow_cross_zone: bool = False) -> int:
    paths = [
        line.strip() for line in Path(changed_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_zone: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        zone = zone_of(path)
        if zone is not None:
            by_zone[zone].append(path)
    for zone, files in sorted(by_zone.items()):
        print(f"[{zone}] {len(files)} files")
        for name in files[:10]:
            print(f"  {name}")
    if len(by_zone) <= 1:
        print("Single-zone or docs-only PR: accepted")
        return 0

    zones = ", ".join(f"{key} {len(files)}" for key, files in sorted(by_zone.items()))
    if allow_cross_zone:
        print(f"::warning::Approved cross-zone exception. Review affected owners: {zones}")
        return 0
    print(f"::error::Unapproved cross-zone PR: {zones}. Split PR or obtain cross-zone-approved label.")
    return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("changed_file")
    parser.add_argument("--allow-cross-zone", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(args.changed_file, allow_cross_zone=args.allow_cross_zone))