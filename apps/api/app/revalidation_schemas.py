"""API schemas for changed-notice qualification revalidation."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from bidengine.diff.requirement_diff import RequirementChange
from .judgment_schemas import QualificationJudgmentRunRead


class QualificationRevalidationCreate(BaseModel):
    source_judgment_run_id: UUID
    baseline_analysis_run_id: UUID | None = None
    current_analysis_run_id: UUID | None = None
    reference_date: date | None = None


class QualificationRevalidationRead(BaseModel):
    id: UUID
    preflight_case_id: UUID
    source_judgment_run_id: UUID
    result_judgment_run_id: UUID
    baseline_analysis_run_id: UUID
    current_analysis_run_id: UUID
    changes: list[RequirementChange] = Field(default_factory=list)
    revalidated_keys: list[str] = Field(default_factory=list)
    created_at: datetime
    result: QualificationJudgmentRunRead
