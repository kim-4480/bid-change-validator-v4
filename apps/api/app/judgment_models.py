"""Persistence models for deterministic qualification judgment runs."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .analysis_models import QualificationAnalysisRun
from .models import Base, Company, PreflightCase


class CompanyQualificationProfileCompleteness(Base):
    __tablename__ = "company_qualification_profile_completeness"

    company_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    region_complete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    company_size_complete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    industries_complete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    staff_total_complete: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    staff_roles_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    performances_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    certifications_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    company: Mapped[Company] = relationship()


class QualificationJudgmentRun(Base):
    __tablename__ = "qualification_judgment_runs"
    __table_args__ = (
        CheckConstraint(
            "overall_status IN ('eligible', 'ineligible', 'insufficient_data')",
            name="qualification_judgment_runs_overall_status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    preflight_case_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("preflight_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    analysis_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
    )
    notice_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    overall_status: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(Text, nullable=False)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    profile_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    analysis_status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    preflight_case: Mapped[PreflightCase] = relationship()
    analysis_run: Mapped[QualificationAnalysisRun] = relationship()
    company: Mapped[Company] = relationship()
    judgments: Mapped[list["QualificationJudgmentRecord"]] = relationship(
        back_populates="judgment_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class QualificationJudgmentRecord(Base):
    __tablename__ = "qualification_judgments"
    __table_args__ = (
        UniqueConstraint(
            "judgment_run_id",
            "requirement_key",
            name="uq_qualification_judgment_run_requirement",
        ),
        CheckConstraint(
            "status IN ('SATISFIED', 'UNSATISFIED', 'UNKNOWN')",
            name="qualification_judgments_status_valid",
        ),
        CheckConstraint(
            "basis_type IN ('PROFILE', 'USER_ANSWER', 'NONE')",
            name="qualification_judgments_basis_type_valid",
        ),
        CheckConstraint(
            "reason_code IN ('RULE_MATCH', 'RULE_MISMATCH', 'INSUFFICIENT_DATA', "
            "'NEEDS_REVIEW', 'UNSUPPORTED_REQUIREMENT')",
            name="qualification_judgments_reason_code_valid",
        ),
        CheckConstraint(
            "value_source IN ('stored_profile', 'askback', 'none')",
            name="qualification_judgments_value_source_valid",
        ),
        CheckConstraint(
            "evidence_status IN ('none', 'declared', 'uploaded')",
            name="qualification_judgments_evidence_status_valid",
        ),
        CheckConstraint(
            "unknown_reason IS NULL OR unknown_reason IN "
            "('profile_missing', 'requirement_uncertain', 'evidence_missing')",
            name="qualification_judgments_unknown_reason_valid",
        ),
        CheckConstraint(
            "(status = 'UNKNOWN' AND unknown_reason IS NOT NULL) OR "
            "(status <> 'UNKNOWN' AND unknown_reason IS NULL)",
            name="qualification_judgments_unknown_reason_consistent",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    judgment_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    judgment_key: Mapped[str] = mapped_column(Text, nullable=False)
    requirement_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    basis_type: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_held: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    value_source: Mapped[str] = mapped_column(Text, default="none", nullable=False)
    evidence_status: Mapped[str] = mapped_column(Text, default="none", nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    unknown_reason: Mapped[str | None] = mapped_column(Text)
    requires_evidence: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    profile_refs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    requirement_evidence_keys: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    rule_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    judgment_run: Mapped[QualificationJudgmentRun] = relationship(
        back_populates="judgments"
    )


Index(
    "idx_qualification_judgment_runs_case_created",
    QualificationJudgmentRun.preflight_case_id,
    QualificationJudgmentRun.created_at.desc(),
)
Index(
    "idx_qualification_judgment_runs_analysis",
    QualificationJudgmentRun.analysis_run_id,
)
Index(
    "idx_qualification_judgments_run_status",
    QualificationJudgmentRecord.judgment_run_id,
    QualificationJudgmentRecord.status,
)
