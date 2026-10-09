"""API schemas for profile completeness and deterministic qualification judgments."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from bidengine.contracts import Judgment
from bidengine.judgment.rules import OverallQualificationStatus, ProfileCompleteness, normalize_overall_status


class QualificationProfileCompletenessRead(BaseModel):
    company_id: UUID
    completeness: ProfileCompleteness
    persisted: bool
    updated_at: datetime | None = None


class QualificationProfileCompletenessUpdate(BaseModel):
    region: bool | None = None
    company_size: bool | None = None
    industries: bool | None = None
    staff_total: bool | None = None
    staff_roles: bool | None = None
    performances: bool | None = None
    certifications: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "QualificationProfileCompletenessUpdate":
        if not self.model_fields_set:
            raise ValueError("at least one completeness field is required")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("completeness fields cannot be null")
        return self


class QualificationJudgmentTrigger(BaseModel):
    analysis_run_id: UUID | None = None
    reference_date: date | None = None


class QualificationJudgmentRunRead(BaseModel):
    id: UUID
    preflight_case_id: UUID
    analysis_run_id: UUID
    company_id: UUID
    notice_version_id: UUID
    overall_status: OverallQualificationStatus
    rule_version: str
    reference_date: date
    analysis_status: str
    profile_completeness: ProfileCompleteness
    profile_snapshot: dict[str, Any]
    judgments: list[Judgment] = Field(default_factory=list)
    created_at: datetime

    @field_validator("overall_status", mode="before")
    @classmethod
    def legacy_verdict_needs_review(cls, value: str) -> OverallQualificationStatus:
        return normalize_overall_status(value)


class QualificationJudgmentRunSummary(BaseModel):
    id: UUID
    analysis_run_id: UUID
    company_id: UUID
    notice_version_id: UUID
    overall_status: OverallQualificationStatus
    rule_version: str
    reference_date: date
    analysis_status: str
    judgment_count: int
    unknown_count: int
    unsatisfied_count: int
    created_at: datetime

    @field_validator("overall_status", mode="before")
    @classmethod
    def legacy_verdict_needs_review(cls, value: str) -> OverallQualificationStatus:
        return normalize_overall_status(value)
