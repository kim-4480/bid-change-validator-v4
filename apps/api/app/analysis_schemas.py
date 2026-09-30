"""API schemas for persisted qualification analysis runs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from bidengine.pipeline.analysis_result import AnalysisDiagnostic, DroppedRequirement
from bidengine.contracts import Evidence, QualificationRequirement


class QualificationAnalysisRunRead(BaseModel):
    id: UUID
    notice_id: UUID
    notice_version_id: UUID
    version_number: int
    contract_version: str
    analysis_kind: str
    status: str
    target_chunk_ids: list[str] = Field(default_factory=list)
    diagnostics: list[AnalysisDiagnostic] = Field(default_factory=list)
    dropped_requirements: list[DroppedRequirement] = Field(default_factory=list)
    requirements: list[QualificationRequirement] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    created_at: datetime


class QualificationAnalysisRunSummary(BaseModel):
    id: UUID
    notice_version_id: UUID
    version_number: int
    contract_version: str
    status: str
    requirement_count: int
    evidence_count: int
    created_at: datetime


class QualificationAnalysisTriggerResponse(BaseModel):
    run: QualificationAnalysisRunRead
    provider: dict[str, Any] = Field(default_factory=dict)
