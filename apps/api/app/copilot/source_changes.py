"""Read-only literal source comparison, separate from extracted rule changes."""

from collections import Counter, defaultdict
from difflib import unified_diff
import re

from bidengine.rag.readiness import digest, snapshot_sources


FIELDS = {
    "indstrytyLmtYn": "업종 제한 표시",
    "bidBeginDt": "전자입찰 시작",
    "bidClseDt": "전자입찰 마감",
    "bidQlfctRgstDt": "참가자격 등록 마감",
    "opengDt": "개찰",
}


def _normalized_line_delta(before: str, after: str) -> tuple[list[str], list[str]]:
    def normalize(text: str) -> Counter:
        rows = []
        for line in text.splitlines():
            if re.fullmatch(r"\s*-\s*\d+\s*-\s*", line):
                continue
            line = re.sub(r"^\s*[가-하][.]\s*", "", line).strip()
            if line:
                rows.append(line)
        return Counter(rows)

    left, right = normalize(before), normalize(after)
    return list((left - right).elements()), list((right - left).elements())


def compare_sources(before, after):
    snapshots = [snapshot_sources(version) for version in (before, after)]
    observations: list[str] = []
    limitations: list[str] = []
    metadata = [getattr(version, "raw_json", None) or {} for version in (before, after)]
    fingerprint = digest({
        "comparison_version": 1,
        "sources": [snapshot.fingerprint for snapshot in snapshots],
        "metadata": [{key: item.get(key) for key in FIELDS} for item in metadata],
    })
    prefix = f"기준 차수 {before.bid_notice_order} → 현재 차수 {after.bid_notice_order}. "
    for key, label in FIELDS.items():
        left, right = metadata[0].get(key), metadata[1].get(key)
        if left != right:
            observations.append(
                prefix + f"수집 메타데이터의 {label}: {left} → {right}. "
                "메타데이터 변경만으로 자격 조건이나 회사 판정이 바뀌었다고 단정할 수 없습니다."
            )

    mapped = []
    for version, snapshot in zip((before, after), snapshots):
        accepted = {record.metadata.document_id for record in snapshot.records}
        documents = defaultdict(list)
        for document in version.documents:
            if str(document.id) in accepted:
                key = "표준공고문" if document.source_field == "stdNtceDocUrl" else document.name
                documents[key].append(document)
        mapped.append(documents)
        limitations.extend(snapshot.limitations)

    equal = changed = 0
    for name in sorted(mapped[0].keys() | mapped[1].keys()):
        left, right = mapped[0].get(name, []), mapped[1].get(name, [])
        if len(left) != 1 or len(right) != 1:
            limitations.append(f"{name}: 두 버전의 대응 문서를 하나로 특정하지 못해 내용 변경 판정을 보류했습니다.")
            continue
        texts = [
            "\n".join(str(block.get("text", "")) for block in document.extracted_blocks if isinstance(block, dict))
            for document in (left[0], right[0])
        ]
        if texts[0] == texts[1]:
            equal += 1
            continue
        changed += 1
        diff = "\n".join(unified_diff(texts[0].splitlines(), texts[1].splitlines(), fromfile="기준 원문", tofile="현재 원문", n=2))
        if len(diff) > 12000:
            limitations.append(f"{name}: 원문 차이가 표시 한도를 넘어 세부 비교를 완료하지 못했습니다.")
            observations.append(prefix + f"{name}의 추출 원문이 서로 다르지만 상세 변경은 미검증입니다.")
            continue
        removed, added = _normalized_line_delta(*texts)
        observations.append(
            prefix + f"{name} 추출 원문 대조입니다. 문구 차이는 구조화된 자격 조건 변경이나 회사 판정 변화와 다릅니다. "
            f"기준에만 있는 문구 {len(removed)}줄, 현재에만 있는 문구 {len(added)}줄입니다.\n"
            + "기준에만 있는 문구: " + "\n".join(removed)
            + "\n현재에만 있는 문구: " + "\n".join(added)
            + "\n원래 표기를 보존한 대조:\n" + diff
        )
    observations.insert(
        0,
        prefix + f"대응 확인된 문서 중 추출 원문 동일 {equal}건, 상이 {changed}건입니다. "
        "추출 텍스트 대조이며 원본 파일 전체·법적 의미·구조화 요건이 동일하다는 뜻은 아닙니다.",
    )
    return fingerprint, observations, list(dict.fromkeys(limitations))
