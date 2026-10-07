"""API schemas for persisted qualification analysis runs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from bidengine.pipeline.analysis_result import AnalysisCoverage, AnalysisDiagnostic, DroppedRequirement
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
    # 확인 항목 공백(checklist_gaps)·참고 정보(notes)·판정을 막는 공백. 2026-10-07 이전 실행은 None.
    coverage: AnalysisCoverage | None = None
    # 판정 대상(닫힌 값) 쪽으로 다 봤는가. None 이면 예전처럼 분석 상태로 판단한다.
    verdict_complete: bool | None = None
    # 요건별 등급: VERDICT(종합 판정에 쓰는 닫힌 값) | CHECKLIST(사용자가 확인할 항목).
    requirement_tiers: dict[str, str] = Field(default_factory=dict)
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
