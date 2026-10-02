"""Response-local references, independent from versioned source identities."""

import json
import re

from ..qualification.judgment import QualificationJudgmentError


REF = re.compile(r"\[(S\d+)\]")


def display_text(text):
    # A literal source quote can itself contain [S1]; it is not our citation.
    return REF.sub(lambda match: f"［{match[1]}］", str(text))


def invalid_mapping():
    return QualificationJudgmentError(
        "COPILOT_SOURCE_MAPPING_INVALID", "응답의 원문 근거 연결을 확인하지 못했습니다.", status_code=500,
    )


def source_identity(source):
    data = source.model_dump(mode="json", exclude={"ref"})
    origin = data["source_origin"]
    evidence = data.get("evidence", data)
    fields = ("source_type", "notice_version_id", "case_id", "document_id", "evidence_key", "chunk_id",
              "location", "page", "clause_label", "source_locations")
    if not evidence.get("notice_version_id") or not evidence.get("document_id"):
        raise invalid_mapping()
    return json.dumps([origin, {key: evidence.get(key) for key in fields}], sort_keys=True, ensure_ascii=False)


class SourceMap:
    def __init__(self):
        self._sources = {}

    def add(self, source):
        identity = source_identity(source)
        if identity in self._sources:
            if self._sources[identity].model_dump(exclude={"ref"}) != source.model_dump(exclude={"ref"}):
                raise invalid_mapping()
        else:
            self._sources[identity] = source.model_copy(deep=True)
        return identity

    def finalize(self, presentation):
        refs = {key: f"S{i}" for i, key in enumerate(self._sources, 1)}
        for reason in presentation.reasons:
            if any(key not in refs for key in reason.evidence_refs):
                raise invalid_mapping()
            reason.evidence_refs = list(dict.fromkeys(refs[key] for key in reason.evidence_refs))
        return [source.model_copy(update={"ref": refs[key]}) for key, source in self._sources.items()]


def cited_sources(answer, presentation, sources):
    mapping = {source.ref: source for source in sources}
    if len(mapping) != len(sources) or list(mapping) != [f"S{i}" for i in range(1, len(sources) + 1)]:
        raise invalid_mapping()
    used = list(dict.fromkeys(REF.findall(answer)))
    reason_refs = {ref for reason in presentation.reasons for ref in reason.evidence_refs}
    if not set(used) <= mapping.keys() or not reason_refs <= set(used):
        raise invalid_mapping()
    return [mapping[ref] for ref in used]
