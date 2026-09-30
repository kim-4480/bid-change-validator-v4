"""Canonical AI contracts shared by backend and LLM/RAG integration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


RequirementType = Literal[
    "PERFORMANCE_AMOUNT",
    "PERFORMANCE_COUNT",
    "INDUSTRY",
    "REGION",
    "STAFF",
    "REGISTRATION_CERTIFICATION",
    "EXPERIENCE_FIELD",
    "COMPANY_SIZE",
]
RequirementOperator = Literal[">=", ">", "<=", "<", "=", "MATCH", "RANGE"]
RequirementRole = Literal["mandatory", "preferred", "informational"]
ConditionComplexity = Literal["simple", "composite"]

JudgmentStatus = Literal["SATISFIED", "UNSATISFIED", "UNKNOWN"]
BasisType = Literal["PROFILE", "USER_ANSWER", "NONE"]
ReasonCode = Literal[
    "RULE_MATCH",
    "RULE_MISMATCH",
    "INSUFFICIENT_DATA",
    "NEEDS_REVIEW",
    "UNSUPPORTED_REQUIREMENT",
]
EvidenceSourceType = Literal["NOTICE_DOCUMENT", "PROPOSAL_DOCUMENT"]
JudgmentValueSource = Literal["stored_profile", "askback", "none"]
EvidenceStatus = Literal["none", "declared", "uploaded"]
UnknownReason = Literal["profile_missing", "requirement_uncertain", "evidence_missing"]

_REASON_MESSAGES: dict[ReasonCode, str] = {
    "RULE_MATCH": "회사 프로필이 공고 조건을 충족합니다.",
    "RULE_MISMATCH": "회사 프로필이 공고 조건을 충족하지 못합니다.",
    "INSUFFICIENT_DATA": "판정에 필요한 회사 정보가 부족합니다.",
    "NEEDS_REVIEW": "조건이 복합적이거나 근거가 불명확하여 직접 확인이 필요합니다.",
    "UNSUPPORTED_REQUIREMENT": "현재 자동 판정을 지원하지 않는 조건입니다.",
}


class EvidenceLocation(BaseModel):
    # Backend extracted_blocks are the source-of-truth locator. The range fields
    # let one semantic citation cover one or more adjacent source blocks without
    # inventing a PDF page for HWP/HWPX documents.
    block_start: int | None = None
    block_end: int | None = None
    page: int | None = None
    section_index: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    source_line_start: int | None = None
    source_line_end: int | None = None
    clause_label: str | None = None
    display: str | None = None


class Evidence(BaseModel):
    evidence_key: str
    source_type: EvidenceSourceType
    document_id: str
    notice_version_id: str | None = None
    case_id: str | None = None
    chunk_id: str | None = None
    location: EvidenceLocation
    quote: str
    # Original file identity and the exact extracted-text identity are kept
    # separately so an evaluation run stays reproducible even if parsers evolve.
    source_sha256: str | None = None
    extracted_text_sha256: str | None = None


class QualificationRequirement(BaseModel):
    requirement_key: str
    requirement_group_key: str | None = None
    group_operator: Literal["ALL_OF", "ANY_OF"] | None = None
    notice_version_id: str
    type: RequirementType
    operator: RequirementOperator | None = None
    value: int | float | str | None = None
    unit: str | None = None
    period_months: float | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    requirement_role: RequirementRole = "mandatory"
    condition_complexity: ConditionComplexity = "simple"
    required: bool = True
    raw: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def synchronize_legacy_required(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        role = data.get("requirement_role")
        required = data.get("required")
        if role is None and required is not None:
            data["requirement_role"] = "mandatory" if required else "preferred"
        elif role is not None and required is None:
            data["required"] = role == "mandatory"
        elif role is not None and required is not None:
            if bool(required) != (role == "mandatory"):
                raise ValueError("required and requirement_role are inconsistent")
        return data


class Judgment(BaseModel):
    judgment_key: str
    preflight_case_id: str
    notice_version_id: str
    requirement_key: str
    status: JudgmentStatus
    basis_type: BasisType
    evidence_held: bool = False
    value_source: JudgmentValueSource | None = None
    evidence_status: EvidenceStatus | None = None
    reason_code: ReasonCode
    unknown_reason: UnknownReason | None = None
    reason: str | None = None
    requires_evidence: bool = False
    profile_refs: list[dict[str, str]] = Field(default_factory=list)
    requirement_evidence_keys: list[str] = Field(default_factory=list)
    rule_version: str | None = None

    @model_validator(mode="after")
    def complete_display_axes(self) -> "Judgment":
        if self.value_source is None:
            self.value_source = {
                "PROFILE": "stored_profile",
                "USER_ANSWER": "askback",
                "NONE": "none",
            }[self.basis_type]
        if self.evidence_status is None:
            self.evidence_status = "declared" if self.evidence_held else "none"
        if self.status == "UNKNOWN" and self.unknown_reason is None:
            self.unknown_reason = (
                "requirement_uncertain"
                if self.reason_code in {"NEEDS_REVIEW", "UNSUPPORTED_REQUIREMENT"}
                else "profile_missing"
            )
        if self.status != "UNKNOWN" and self.unknown_reason is not None:
            raise ValueError("unknown_reason is only valid for UNKNOWN judgments")
        if self.reason is None:
            self.reason = _REASON_MESSAGES[self.reason_code]
        return self
