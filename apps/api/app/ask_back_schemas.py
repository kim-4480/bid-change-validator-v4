from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel
from .judgment_schemas import QualificationJudgmentRunRead


class QualificationQuestionRead(BaseModel):
    requirement_key: str
    requirement_type: str
    question: str
    raw_requirement: str
    askable: bool = True
    askability_reason_code: str = "ASKABLE_SIMPLE_FACT"
    askability_reason: str = ""


class QualificationAnswerCreate(BaseModel):
    source_judgment_run_id: UUID
    requirement_key: str
    satisfies_requirement: bool
    normalized_value: str | None = None
    evidence_held: bool = False
    apply_to_profile: bool = False


class QualificationAnswerRead(BaseModel):
    id: UUID
    preflight_case_id: UUID
    source_judgment_run_id: UUID
    result_judgment_run_id: UUID
    requirement_key: str
    answer: dict[str, Any]
    normalized_value: str | None
    evidence_held: bool
    apply_to_profile: bool
    created_at: datetime
    result: QualificationJudgmentRunRead
