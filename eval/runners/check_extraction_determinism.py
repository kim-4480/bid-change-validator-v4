"""같은 공고를 N 번 추출해서 **결과가 같은지** 잰다.

왜 따로 있나
------------
단위 테스트(`test_extraction_determinism.py`)는 요청에 temperature·seed 가 실려 나가는지만
본다. 그것이 실제로 같은 출력을 내는지는 모델을 불러야 알 수 있고, DB 와 API 키가 필요해
CI 밖이다.

2026-09-14 기준 R26BK01633750 의 DB 기록 14건은 청크 39개가 매번 동일한데 요건 개수가
1·3·0·0·0·2·0·0·0·0·3·1·0·2 였다. 그 흔들림이 멈췄는지를 여기서 확인한다.

무엇을 비교하나
--------------
요건 개수만 보면 "3건 / 3건" 이 같아 보여도 내용이 다를 수 있다. 그래서 세 층을 따로 센다.

    요건 집합     (type, value, raw) 정규화 후 정렬 — 내용까지 같은가
    버림 집합     근거 검증이 버린 것과 그 사유
    미분류 집합   공고 사실로만 본 원문

한 층이라도 실행마다 다르면 불안정이다. 어느 층이 흔들리는지가 고칠 자리를 가른다 —
요건 집합이 흔들리면 모델·프롬프트, 버림 집합만 흔들리면 근거 검증이다.

    python scripts/check_extraction_determinism.py --source-id 01633750-002 --runs 5
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import time
import unicodedata
from datetime import datetime
from datetime import timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "eval" / "golden" / "qualification-v0.2"
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def load_env(env_file: Path) -> None:
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def normalize(text: object) -> str:
    """비교용. 공백과 호환 문자 차이로 '다르다' 가 나오면 측정이 못 쓴다."""
    if text is None:
        return ""
    return "".join(unicodedata.normalize("NFKC", str(text)).split())


def fingerprint(items: list[str]) -> str:
    """순서에 상관없이 집합이 같으면 같은 지문."""
    joined = "\x1f".join(sorted(items))  # 원문에 나올 리 없는 구분자
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


def layers(result) -> dict[str, list[str]]:
    return {
        "요건": [
            f"{item.type}|{normalize(item.value)}|{normalize(item.raw)}"
            for item in result.requirements
        ],
        "버림": [
            f"{getattr(item, 'reason_code', '')}|{getattr(item, 'detail_field', '') or ''}"
            f"|{normalize(getattr(item, 'detail_value', '') or '')}"
            f"|{normalize(getattr(item, 'raw', ''))}"
            for item in result.dropped_requirements
        ],
        "미분류": [
            normalize((item.details or {}).get("raw"))
            for item in result.diagnostics
            if item.code == "UNMAPPED_REQUIREMENT" and (item.details or {}).get("raw")
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-id", required=True, help="골든셋 source_id (예: 01633750-002)")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--golden-dir", type=Path, default=GOLDEN_DIR)
    ap.add_argument("--model", default=None, help="모델을 바꿔 비교할 때 (기본: OPENAI_MODEL_DEFAULT)")
    ap.add_argument("--temperature", type=float, default=None,
                    help="기본은 결정성 고정값 0. 분산을 일부러 볼 때만 올린다")
    ap.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    load_env(args.env_file)

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from bidengine.providers.openai import OpenAIStructuredExtractor
    from bidengine.pipeline.analysis_pipeline import (
        analyze_qualification_documents,
    )
    from app.database import SessionLocal
    from app.models import BidNoticeVersion
    from app.qualification.analysis import build_qualification_analysis_input

    bundle = json.loads((args.golden_dir / "fixture_bundle.json").read_text(encoding="utf-8"))
    version_id = next(
        (case["notice_version_id"] for case in bundle["cases"]
         if case["source_id"] == args.source_id),
        None,
    )
    if version_id is None:
        raise SystemExit(f"골든셋에 {args.source_id} 가 없습니다.")

    extractor = OpenAIStructuredExtractor(
        model=args.model, temperature=args.temperature
    )
    if not extractor.available:
        raise SystemExit("OPENAI_API_KEY 가 필요합니다.")
    print(f"모델 {extractor.model} · temperature {extractor.temperature} · seed {extractor.seed}")

    db = SessionLocal()
    try:
        version = db.scalar(
            select(BidNoticeVersion)
            .where(BidNoticeVersion.id == version_id)
            .options(selectinload(BidNoticeVersion.documents))
        )
        if version is None:
            raise SystemExit(f"{version_id} 를 DB 에서 못 찾았습니다.")
        analysis_input = build_qualification_analysis_input(version)

        records = []
        for index in range(args.runs):
            started = time.perf_counter()
            result = analyze_qualification_documents(
                analysis_input, structured_extract=extractor
            )
            elapsed = round(time.perf_counter() - started, 1)
            shape = layers(result)
            records.append({
                "run_index": index,
                "elapsed_seconds": elapsed,
                "status": result.status,
                "system_fingerprint": extractor.last_system_fingerprint,
                "counts": {name: len(rows) for name, rows in shape.items()},
                "fingerprints": {name: fingerprint(rows) for name, rows in shape.items()},
                "layers": shape,
            })
            print(
                f"  run{index}  {result.status:<10} {elapsed:>6.1f}s  "
                + "  ".join(
                    f"{name} {len(rows):>2}({fingerprint(rows)})"
                    for name, rows in shape.items()
                ),
                flush=True,
            )
    finally:
        db.close()

    print()
    unstable = []
    for name in ("요건", "버림", "미분류"):
        seen = collections.Counter(record["fingerprints"][name] for record in records)
        if len(seen) > 1:
            unstable.append(name)
            print(f"  [불안정] {name}: 서로 다른 결과 {len(seen)}가지 — "
                  + ", ".join(f"{digest}×{count}" for digest, count in seen.most_common()))
        else:
            print(f"  [고정] {name}: {args.runs}회 모두 동일")

    fingerprints = {record["system_fingerprint"] for record in records}
    if len(fingerprints) > 1:
        print(f"  ! 모델 배치 지문이 실행 중에 바뀌었습니다: {fingerprints}")
        print("    같은 seed 라도 이때는 결과가 달라질 수 있습니다. 우리 코드 탓이 아닙니다.")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "source_id": args.source_id,
            "runs": args.runs,
            "model": extractor.model,
            "temperature": extractor.temperature,
            "seed": extractor.seed,
            "unsupported_parameters": list(extractor.unsupported_parameters),
            "unstable_layers": unstable,
            "records": records,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n-> {args.out}")

    if extractor.unsupported_parameters:
        print(f"\n  ! 모델이 {', '.join(extractor.unsupported_parameters)} 를 받지 않습니다. "
              "결정성이 걸리지 않은 상태입니다.")
    return 1 if unstable else 0


if __name__ == "__main__":
    raise SystemExit(main())
