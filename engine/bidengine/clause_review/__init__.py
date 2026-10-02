"""Contract-clause review core.

This package is intentionally independent from DB/API integration. It reviews
notice contract terms against deterministic patterns and published standards.
LLM/embedding evidence fallback is integrated separately after the extraction
package boundary is stabilized in Baseline v2.
"""

from bidengine.clause_review.contracts import (
    CATEGORY_BY_RULE,
    CATEGORY_LABELS,
    VERDICT_LABELS,
    VERDICT_PRIORITY,
    ClauseFinding,
    ClauseVerdict,
    CategoryCode,
    StandardReference,
    apply_overlapping_categories,
    finding_to_payload,
    overlapping_categories,
)
from bidengine.clause_review.embedding_fallback import make_embedding_fallback
from bidengine.clause_review.pattern_match import detect_patterns
from bidengine.clause_review.standard_diff import RULES, detect_standard_diff, infer_contract_scope, scope_for_notice

__all__ = [
    "ClauseFinding",
    "ClauseVerdict",
    "CategoryCode",
    "CATEGORY_BY_RULE",
    "CATEGORY_LABELS",
    "StandardReference",
    "apply_overlapping_categories",
    "finding_to_payload",
    "overlapping_categories",
    "VERDICT_LABELS",
    "VERDICT_PRIORITY",
    "detect_patterns",
    "detect_standard_diff",
    "infer_contract_scope",
    "scope_for_notice",
    "make_embedding_fallback",
    "RULES",
]
