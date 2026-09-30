"""Versioned conversation contracts; server facts and generated claims stay separate."""
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .contracts import ActionProposal, ProductProvenance


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Scope(Contract):
    case_id: UUID
    company_id: UUID | None
    notice_id: UUID
    notice_version_id: UUID
    analysis_run_id: UUID | None = None
    judgment_run_id: UUID | None = None


class Fact(Contract):
    fact_id: str
    kind: Literal['SERVER_RESULT', 'NOTICE_FACT', 'PROFILE_FACT', 'USER_ASSERTION', 'ASSUMPTION']
    text: str
    source_ids: list[str] = Field(default_factory=list)
    requirement_key: str | None = None
    target_kind: Literal['REQUIREMENT', 'MANUAL', 'DOCUMENT', 'CHANGE', 'ASSUMPTION'] = 'DOCUMENT'
    scope: Scope


class Source(Contract):
    source_id: str
    kind: Literal['DOCUMENT', 'PRODUCT', 'TURN']
    quote: str
    scope: Scope
    document_id: str | None = None
    location: dict[str, Any] = Field(default_factory=dict)
    source_sha256: str | None = None
    extracted_sha256: str | None = None


class Task(Contract):
    kind: Literal['READ_JUDGMENT', 'READ_PROFILE', 'READ_CHECKS', 'READ_DOCUMENT', 'READ_CHANGES', 'REVIEW_ASSUMPTION', 'PROPOSE_ACTION']
    question: str = Field(max_length=4000)
    scope_ref: Literal['current_case'] = 'current_case'


class TaskPlan(Contract):
    goal: str = Field(max_length=4000)
    tasks: list[Task] = Field(min_length=1, max_length=6)
    clarification: str | None = None


class EvidenceBundle(Contract):
    scope: Scope
    server_context: dict[str, Any] = Field(default_factory=dict)
    facts: list[Fact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    coverage: dict[str, str] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    capabilities: dict[str, int] = Field(default_factory=dict)
    fingerprints: dict[str, str] = Field(default_factory=dict)


class Claim(Contract):
    claim_id: str
    text: str = Field(min_length=1, max_length=3000)
    fact_ids: list[str] = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)
    validation: Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT', 'UNCHECKED'] = 'UNCHECKED'
    method: Literal['rule', 'extractive', 'semantic'] = 'semantic'
    reason: str = ''


class DraftClaim(Contract):
    claim_id: str
    text: str = Field(min_length=1, max_length=3000)
    fact_ids: list[str]
    source_ids: list[str]


class Draft(Contract):
    claims: list[DraftClaim] = Field(max_length=60)


class CandidateClaim(DraftClaim):
    """Internal validation record; invalid references never enter AnswerEnvelope."""
    validation: Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT', 'UNCHECKED'] = 'UNCHECKED'
    method: Literal['semantic'] = 'semantic'
    reason: str = ''


class ClaimVerdict(Contract):
    claim_id: str
    status: Literal['SUPPORTED', 'CONTRADICTED', 'INSUFFICIENT']
    reason: str


class Verdicts(Contract):
    verdicts: list[ClaimVerdict]
    task_coverage: Literal['COMPLETE', 'PARTIAL', 'UNKNOWN'] = 'UNKNOWN'
    missing_topics: list[str] = Field(default_factory=list, max_length=20)


class Target(Contract):
    target_id: str
    kind: str
    label: str
    message_id: str
    ordinal: int
    fact_ids: list[str]
    source_ids: list[str]
    requirement_key: str | None = None


class StatusCard(Contract):
    status: str
    text: str
    provenance: ProductProvenance


class Processing(Contract):
    path: Literal['v3.1'] = 'v3.1'
    model: str | None = None
    fallback: bool = False
    task_status: Literal['PASS', 'PARTIAL', 'FAIL'] = 'PARTIAL'
    elapsed_ms: int = 0
    calls: list[dict[str, Any]] = Field(default_factory=list)
    validation_events: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    plan: dict[str, Any] = Field(default_factory=dict)
    deadline_seconds: int = 45
    storage: str = 'process-memory; restart clears history; one worker only'


class GuidedTurn(Contract):
    job_id: str
    question_id: str
    status: Literal['COMPLETE', 'PARTIAL', 'BLOCKED']
    next_question_id: str | None = None


class AnswerEnvelope(Contract):
    version: Literal['3.1'] = '3.1'
    conversation_id: UUID
    context_revision: int
    message_id: str
    status_card: StatusCard | None = None
    claims: list[Claim] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    follow_up_targets: list[Target] = Field(default_factory=list)
    actions: list[ActionProposal] = Field(default_factory=list)
    capabilities: dict[str, int] = Field(default_factory=dict)
    clarification: str | None = None
    guided: GuidedTurn | None = None
    processing: Processing = Field(default_factory=Processing)


class Message(Contract):
    turn_id: str
    question: str
    answer: str
    scope: Scope


class ConversationState(Contract):
    conversation_id: UUID
    owner: str
    scope: Scope
    context_revision: int = 0
    messages: list[Message] = Field(default_factory=list)
    targets: list[Target] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    fingerprints: dict[str, str] = Field(default_factory=dict)
