"""Persistence for ask-back answers and partial re-judgment links."""
from datetime import datetime
from uuid import UUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column
from .models import Base

class QualificationAnswer(Base):
    __tablename__ = "qualification_answers"
    __table_args__ = (UniqueConstraint("source_judgment_run_id","requirement_key",name="uq_qualification_answer_source_requirement"),)
    id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    preflight_case_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), ForeignKey("preflight_cases.id", ondelete="CASCADE"), nullable=False)
    source_judgment_run_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"), nullable=False)
    result_judgment_run_id: Mapped[UUID | None] = mapped_column(PostgresUUID(as_uuid=True), ForeignKey("qualification_judgment_runs.id", ondelete="SET NULL"))
    requirement_key: Mapped[str] = mapped_column(Text, nullable=False)
    answer_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text)
    evidence_held: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    apply_to_profile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

Index("idx_qualification_answers_case_created", QualificationAnswer.preflight_case_id, QualificationAnswer.created_at.desc())
