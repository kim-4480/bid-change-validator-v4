"""API schemas for persisted contract-clause review results."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from bidengine.clause_review.contracts import ClauseFinding


class ContractClauseReviewCreate(BaseModel):
    status: Literal["SUCCEEDED", "PARTIAL", "FAILED"] = "SUCCEEDED"
    findings: list[ClauseFinding] = Field(default_factory=list)


class ContractClauseFindingRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    review_run_id: UUID
    category: str
    categories: list[str] = Field(default_factory=list)
    rule_id: str | None
    risk_type: str
    risk_types: list[str] = Field(default_factory=list)
    detection_method: str
    matched_via: str | None
    verdict: str
    reason: str
    matched_text: str | None
    rfp_clause_label: str | None
    rfp_chunk_id: str | None
    rfp_excerpt: str | None
    rfp_value: dict | None
    standard: dict | None
    form: str | None
    created_at: datetime


class ContractClauseReviewRead(BaseModel):
    id: UUID
    notice_id: UUID
    notice_version_id: UUID
    version_number: int
    status: str
    findings: list[ContractClauseFindingRead] = Field(default_factory=list)
    created_at: datetime


class ContractClauseReviewSummary(BaseModel):
    id: UUID
    notice_version_id: UUID
    version_number: int
    status: str
    finding_count: int
    needs_review_count: int
    created_at: datetime
