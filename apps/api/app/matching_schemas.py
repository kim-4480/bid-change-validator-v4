from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class NoticeMatchRead(BaseModel):
    notice_id: UUID
    bid_notice_no: str
    title: str
    institution_name: str | None
    version_number: int
    analysis_run_id: UUID
    analysis_status: str
    overall_status: Literal["eligible", "ineligible", "insufficient_data"]
    satisfied_count: int
    unknown_count: int
    unsatisfied_count: int
    requirement_count: int
    evidence_count: int
    analyzed_at: datetime


class NoticeMatchSearchResponse(BaseModel):
    company_id: UUID
    analyzed_notice_count: int
    returned_count: int
    items: list[NoticeMatchRead] = Field(default_factory=list)
    note: str = "이미 자격요건 분석 결과가 있는 현재 공고만 비교합니다. 분석되지 않은 공고를 자동 매칭된 것으로 간주하지 않습니다."
