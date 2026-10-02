"""Persistence model for changed-notice qualification revalidation lineage."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class QualificationRevalidationRun(Base):
    __tablename__ = "qualification_revalidation_runs"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    preflight_case_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("preflight_cases.id", ondelete="CASCADE"), nullable=False
    )
    source_judgment_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"), nullable=False
    )
    result_judgment_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"), nullable=False
    )
    baseline_analysis_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    current_analysis_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    changes: Mapped[list] = mapped_column(JSONB, nullable=False)
    revalidated_keys: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


Index(
    "idx_qualification_revalidation_runs_case_created",
    QualificationRevalidationRun.preflight_case_id,
    QualificationRevalidationRun.created_at.desc(),
)
