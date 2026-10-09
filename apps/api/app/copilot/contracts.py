"""Product results preserve backend decisions and their provenance."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from bidengine.contracts import (
    Evidence,
    Judgment,
    JudgmentStatus,
    QualificationRequirement,
    RequirementType,
)
from bidengine.pipeline.analysis_result import AnalysisDiagnostic, DroppedRequirement
from ..ask_back_schemas import QualificationQuestionRead
from bidengine.judgment.rules import OverallQualificationStatus, ProfileCompleteness, normalize_overall_status


class ProductProvenance(BaseModel):
    case_id: UUID
    notice_id: UUID
    notice_version_id: UUID
    version_number: int
    company_id: UUID
    analysis_run_id: UUID
    judgment_run_id: UUID
    analysis_status: Literal["SUCCEEDED", "PARTIAL"]
    rule_version: str


class RequirementJudgmentSummary(Judgment):
    type: RequirementType
    raw: str


class AnalysisNoticeFact(BaseModel):
    """Read-only context, never an ask-back requirement or ordinal target."""
    code: str
    message: str
    evidence: list[Evidence] = Field(default_factory=list)


class AnalysisScope(BaseModel):
    analysis_run_id: UUID
    notice_facts: list[AnalysisNoticeFact] = Field(default_factory=list)
    dropped_requirements: list[DroppedRequirement] = Field(default_factory=list)
    pipeline_diagnostics: list[AnalysisDiagnostic] = Field(default_factory=list)


class QualificationSummary(BaseModel):
    provenance: ProductProvenance
    overall_status: OverallQualificationStatus
    analysis_status: Literal["SUCCEEDED", "PARTIAL"]
    judgment_counts: dict[JudgmentStatus, int]
    judgments: list[RequirementJudgmentSummary]
    analysis_scope: AnalysisScope | None = None

    @field_validator("overall_status", mode="before")
    @classmethod
    def legacy_verdict_needs_review(cls, value: str) -> OverallQualificationStatus:
        return normalize_overall_status(value)


class RequirementEvidenceResult(BaseModel):
    provenance: ProductProvenance
    requirement: QualificationRequirement
    evidence: list[Evidence]


class RequiredChecksResult(BaseModel):
    provenance: ProductProvenance
    questions: list[QualificationQuestionRead]
    user_answer_requires_askable: Literal[True] = Field(
        default=True,
        description="Only askable=true permits a user-answer action; other UNKNOWNs require source review.",
    )


class JudgmentProfileResult(BaseModel):
    provenance: ProductProvenance
    profile_snapshot: dict[str, Any]
    profile_completeness: ProfileCompleteness


class ActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    satisfies_requirement: StrictBool
    normalized_value: str | None = Field(default=None, max_length=2000)
    evidence_held: StrictBool = False
    apply_to_profile: Literal[False] = False


class VersionState(BaseModel):
    notice_version_id: UUID
    version_number: int
    analysis_run_id: UUID
    analysis_status: Literal["SUCCEEDED", "PARTIAL"]
    judgment_run_id: UUID | None


class RevalidationProvenance(BaseModel):
    case_id: UUID
    notice_id: UUID
    company_id: UUID
    baseline: VersionState
    current: VersionState
    rule_version: str


class AnswerProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["ANSWER_REQUIREMENT"] = "ANSWER_REQUIREMENT"
    expected: ProductProvenance
    requirement_key: str = Field(min_length=1, max_length=200)
    user_input: ActionInput
    title: str = "요건 답변 적용"
    consequences: str = "선택한 요건의 사용자 답변으로 새 판정을 저장합니다. 회사 프로필은 변경하지 않습니다."


class RevalidationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action_type: Literal["REVALIDATE"] = "REVALIDATE"
    expected: RevalidationProvenance
    title: str = "변경공고 재검증"
    consequences: str = "기준 판정에서 변경된 요건을 재검증하여 현재 버전의 새 판정을 저장합니다."


ActionProposal = Annotated[AnswerProposal | RevalidationProposal, Field(discriminator="action_type")]


class ConfirmAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    action: ActionProposal

    @field_validator("confirmed", mode="before")
    @classmethod
    def require_explicit_true(cls, value):
        if value is not True:
            raise ValueError("confirmed must be the boolean true")
        return value


class FreeChatTurn(BaseModel):
    """자유 대화의 앞선 한 턴. 문맥으로만 쓰고 사실의 출처로 쓰지 않는다(free_chat.py)."""
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(max_length=8000)
