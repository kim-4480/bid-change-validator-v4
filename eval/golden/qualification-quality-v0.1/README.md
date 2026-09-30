# Qualification quality harness v0.1

This is a synthetic harness check, **not a real-notice benchmark or model score**.
It starts from handwritten extracted blocks. It does not assess binary parsing,
call a model, access a database, seed Product data, or import Demo code.

```bash
python -m apps.api.app.scripts.quality_eval_report --dataset samples/golden/qualification-quality-v0.1
python -m apps.api.app.scripts.quality_eval_report --dataset samples/golden/qualification-quality-v0.1 --synthetic-extraction
```

The default measures selection only. The explicit synthetic option injects fixed
slots into the existing public Core pipeline. Expected labels and injected slots
serve different purposes, but both are handwritten; passing proves harness wiring
and existing deterministic behavior, not LLM extraction quality.

The manifest pins case/notice/version/document identities and SHA-256 hashes of
every referenced JSON file. Extracted text hash uses UTF-8 block texts joined by a
single newline. Original file hashes stay null for these synthetic blocks. Do not
substitute the blocks JSON hash for an original document hash. The three profile
variants are reserved metadata, not executed CompanyProfileSnapshot fixtures.

POSITIVE means a source condition should survive, including unmapped conditions.
TRAP means a reviewed non-qualification span. Empty expected fields mean canonical
matching is unmeasured; an explicitly present null must match null. Scope and group
operator expectations are compared exactly. Duplicate IDs, invalid document/version
links, missing quotes, escaping paths, and hash mismatches are rejected.

Selection recall counts labeled spans; precision counts selected chunks with a
positive label; trap rate counts selected labeled traps. Sparse labels are not an
exhaustive relevance judgment. Context recall includes the actual serialized header
lengths and 32,000-character truncation. Evidence and canonical matches require the
same document, quote, and linked evidence. This is text containment, not exact
character-offset grounding or one-to-one requirement alignment.

Ratios include numerator and denominator. A zero denominator or unmeasured stage is
null with a reason. Retry/drop rates remain null because Core has no complete trace.
The report is per-case; no promotion threshold or model quality claim is made.

Real-notice evaluation requires separately reviewed source snapshots, explicit
provenance, fixed notice versions, multiple companies/notices, change cases, and
labels approved independently of model output. Product execution IDs should later
be recorded in a separate run manifest, not invented by this offline runner.
