"""Label-based metrics. Missing measurements stay null, never synthetic zeros."""

import statistics

from bidengine.labeling.requirement_extraction import build_extraction_body


def ratio(numerator, denominator, reason="empty denominator"):
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None,
            "reason": None if denominator else reason}


def context_chunks(selected, budget=32_000):
    """Clip each document's text to its actual position in the serialized body."""
    chunks = []
    offset = 0
    for chunk in selected:
        part = build_extraction_body([chunk], max_chars=None)
        header_size = len(part) - len(chunk["text"])
        visible = max(0, budget - offset - header_size)
        chunks.append({**chunk, "text": chunk["text"][:visible]})
        offset += len(part) + 2
    return chunks


def has_span(chunk, span):
    return (span.document_id in {b.get("document_id") for b in chunk["source_blocks"]}
            and span.is_in(chunk["text"]))


def score_case(spans, chunks, selected, result=None, budget=32_000):
    if budget <= 0:
        raise ValueError("context budget must be positive")
    context = context_chunks(selected, budget)
    positives = [s for s in spans if s.span_kind == "POSITIVE"]
    traps = [s for s in spans if s.span_kind == "TRAP"]
    rows = []
    for span in positives:
        evidence = [] if result is None else [e for e in result.evidence
                    if e.document_id == span.document_id and span.is_in(e.quote)]
        keys = {e.evidence_key for e in evidence}
        matched = [] if result is None else [r for r in result.requirements
                   if keys.intersection(r.evidence_keys) and span.is_in(r.raw)
                   and all(r.model_dump()[key] == value for key, value in span.expected.items())]
        rows.append({"span_id": span.span_id,
                     "contained": any(has_span(c, span) for c in chunks),
                     "selected": any(has_span(c, span) for c in selected),
                     "in_context": any(has_span(c, span) for c in context),
                     "evidence_preserved": None if result is None else bool(evidence),
                     "canonical_match": None if result is None or not span.expected else bool(matched)})
    lengths = [len(c["text"]) for c in chunks]
    full_size = len(build_extraction_body(selected, max_chars=None))
    metrics = {name: ratio(sum(row[field] for row in rows), len(rows))
               for name, field in [("span_containment", "contained"),
                                   ("selection_recall", "selected"),
                                   ("context_recall", "in_context")]}
    metrics["selection_precision"] = ratio(sum(any(has_span(c, s) for s in positives)
                                                for c in selected), len(selected))
    if not spans:
        metrics["selection_precision"] = {"numerator": None, "denominator": None,
                                          "value": None, "reason": "no ground truth labels"}
    metrics["trap_selection_rate"] = ratio(sum(any(has_span(c, s) for c in selected)
                                               for s in traps), len(traps))
    for field in ["canonical_match", "evidence_preserved"]:
        measured = [r[field] for r in rows if r[field] is not None]
        metrics[field] = ratio(sum(measured), len(measured), "stage not run or no applicable labels")
    return {"metrics": metrics, "spans": rows,
            "chunk_health": {"count": len(chunks), "median_chars": statistics.median(lengths) if lengths else None,
                             "under_50": sum(n < 50 for n in lengths), "over_1800": sum(n > 1800 for n in lengths)},
            "context": {"full_chars": full_size, "sent_chars": min(full_size, budget),
                        "truncated_chars": max(0, full_size - budget),
                        "budget_utilization": ratio(min(full_size, budget), budget)},
            "analysis_status": None if result is None else result.status,
            "retry_rate": {"numerator": None, "denominator": None, "value": None,
                           "reason": "Core exposes no complete attempt trace"},
            "drop_rate": {"numerator": None, "denominator": None, "value": None,
                          "reason": "Core exposes no structured drop ledger"}}
