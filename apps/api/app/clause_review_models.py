"""Persistence models for contract-clause review runs and findings."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .models import Base, BidNoticeVersion


class ContractClauseReviewRun(Base):
    __tablename__ = "contract_clause_review_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="contract_clause_review_runs_status_valid",
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
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    notice_version: Mapped[BidNoticeVersion] = relationship()
    findings: Mapped[list["ContractClauseFindingRecord"]] = relationship(
        back_populates="review_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ContractClauseFindingRecord(Base):
    __tablename__ = "contract_clause_findings"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('확인 필요', '적합', '확인 불가')",
            name="contract_clause_findings_verdict_valid",
        ),
        CheckConstraint(
            "detection_method IN ('standard_diff', 'pattern_match')",
            name="contract_clause_findings_method_valid",
        ),
        CheckConstraint(
            "category IN ('WARRANTY_PERIOD', 'LATE_PENALTY', 'LATE_PENALTY_RATE', "
            "'COPYRIGHT_OWNERSHIP', 'ACCEPTANCE_CRITERIA', 'SCOPE_AMBIGUITY', "
            "'PAYMENT_TERMS', 'LIABILITY_SCOPE', 'TERMINATION_CONDITION')",
            name="contract_clause_findings_category_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    review_run_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("contract_clause_review_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    category: Mapped[str] = mapped_column(Text, nullable=False)
    categories: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    rule_id: Mapped[str | None] = mapped_column(Text)
    risk_type: Mapped[str] = mapped_column(Text, nullable=False)
    risk_types: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    detection_method: Mapped[str] = mapped_column(Text, nullable=False)
    matched_via: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    matched_text: Mapped[str | None] = mapped_column(Text)
    rfp_clause_label: Mapped[str | None] = mapped_column(Text)
    rfp_chunk_id: Mapped[str | None] = mapped_column(Text)
    rfp_excerpt: Mapped[str | None] = mapped_column(Text)
    rfp_value: Mapped[dict | None] = mapped_column(JSONB)
    standard: Mapped[dict | None] = mapped_column(JSONB)
    form: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    review_run: Mapped[ContractClauseReviewRun] = relationship(back_populates="findings")


Index(
    "idx_contract_clause_review_runs_version_created",
    ContractClauseReviewRun.notice_version_id,
    ContractClauseReviewRun.created_at,
)
Index("idx_contract_clause_findings_run", ContractClauseFindingRecord.review_run_id)
Index(
    "idx_contract_clause_findings_category_verdict",
    ContractClauseFindingRecord.category,
    ContractClauseFindingRecord.verdict,
)
