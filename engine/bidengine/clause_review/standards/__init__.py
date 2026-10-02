"""The published government contract rules, indexed and read for thresholds.

`index` turns extracted rule text into clauses; `values` reads each rule's
comparison threshold out of those clauses. No figure used for judging is written
in this package — only where in the rule text to find it.
"""

from bidengine.clause_review.standards.index import build_clause_index, find_clause, load_clauses, split_clauses
from bidengine.clause_review.standards.values import (
    CONTRACT_SCOPES,
    SCOPE_LABELS,
    SPECS,
    format_value,
    resolve_all,
    resolve_standard_value,
    select_variant,
)

__all__ = [
    "build_clause_index",
    "split_clauses",
    "load_clauses",
    "find_clause",
    "SPECS",
    "CONTRACT_SCOPES",
    "SCOPE_LABELS",
    "select_variant",
    "resolve_standard_value",
    "resolve_all",
    "format_value",
]
