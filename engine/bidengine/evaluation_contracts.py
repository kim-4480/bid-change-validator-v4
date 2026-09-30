"""Source-grounded evaluation criteria contract.

This contract is deliberately separate from qualification Requirements.  It
represents what the notice says about evaluation without predicting a bidder's
score.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


EvaluationMethod = Literal[
    "QUANTITATIVE",
    "QUALITATIVE",
    "PASS_FAIL",
    "PRESENTATION",
    "OTHER",
]


class EvaluationCriterion(BaseModel):
    criterion_key: str
    notice_version_id: str
    title: str
    raw: str
    max_score: float | None = Field(default=None, ge=0)
    evaluation_method: EvaluationMethod = "OTHER"
    response_fields: list[str] = Field(default_factory=list)
    evidence_keys: list[str] = Field(default_factory=list)


class EvaluationAnalysisResult(BaseModel):
    notice_id: str
    notice_version_id: str
    criteria: list[EvaluationCriterion] = Field(default_factory=list)
    evidence_keys: list[str] = Field(default_factory=list)
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"]
    diagnostics: list[dict[str, str]] = Field(default_factory=list)
