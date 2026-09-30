"""Persistence models for canonical qualification analysis outputs.

These models intentionally live outside ``models.py`` to keep the MVP integration
surface small while the Backend/DB contract is being stabilized.
"""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .models import Base, BidNoticeVersion


class QualificationAnalysisRun(Base):
    __tablename__ = "qualification_analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="qualification_analysis_runs_status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    notice_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    contract_version: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    target_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list)
    diagnostics: Mapped[list] = mapped_column(JSONB, default=list)
    dropped_requirements: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    notice_version: Mapped[BidNoticeVersion] = relationship()
    requirements: Mapped[list["QualificationRequirementRecord"]] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True
    )
    evidence: Mapped[list["QualificationEvidenceRecord"]] = relationship(
        back_populates="analysis_run", cascade="all, delete-orphan", passive_deletes=True
    )


class QualificationRequirementRecord(Base):
    __tablename__ = "qualification_requirements"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id", "requirement_key", name="uq_qualification_requirement_run_key"
        ),
        CheckConstraint(
            "requirement_role IN ('mandatory', 'preferred', 'informational')",
            name="qualification_requirements_role_valid",
        ),
        CheckConstraint(
            "condition_complexity IN ('simple', 'composite')",
            name="qualification_requirements_complexity_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_key: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_group_key: Mapped[str | None] = mapped_column(Text)
    group_operator: Mapped[str | None] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    operator: Mapped[str | None] = mapped_column(Text)
    value_json: Mapped[object | None] = mapped_column(JSONB)
    unit: Mapped[str | None] = mapped_column(Text)
    period_months: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    requirement_role: Mapped[str] = mapped_column(Text, default="mandatory", nullable=False)
    condition_complexity: Mapped[str] = mapped_column(Text, default="simple", nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    raw: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(6, 5))
    evidence_keys: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    analysis_run: Mapped[QualificationAnalysisRun] = relationship(back_populates="requirements")


class QualificationEvidenceRecord(Base):
    __tablename__ = "qualification_evidence"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id", "evidence_key", name="uq_qualification_evidence_run_key"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str] = mapped_column(Text, nullable=False)
    notice_version_id: Mapped[str | None] = mapped_column(Text)
    case_id: Mapped[str | None] = mapped_column(Text)
    chunk_id: Mapped[str | None] = mapped_column(Text)
    location: Mapped[dict] = mapped_column(JSONB, default=dict)
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(Text)
    extracted_text_sha256: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    analysis_run: Mapped[QualificationAnalysisRun] = relationship(back_populates="evidence")


Index(
    "idx_qualification_analysis_runs_version_created",
    QualificationAnalysisRun.notice_version_id,
    QualificationAnalysisRun.created_at.desc(),
)
Index(
    "idx_qualification_requirements_run_type",
    QualificationRequirementRecord.analysis_run_id,
    QualificationRequirementRecord.type,
)
Index(
    "idx_qualification_evidence_run",
    QualificationEvidenceRecord.analysis_run_id,
)
