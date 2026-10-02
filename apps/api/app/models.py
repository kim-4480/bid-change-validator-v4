from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class IndustryCode(Base):
    __tablename__ = "industry_codes"
    __table_args__ = (Index("idx_industry_codes_name", "name"),)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_window: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict] = mapped_column(JSONB)


class ProductCode(Base):
    __tablename__ = "product_codes"
    __table_args__ = (Index("idx_product_codes_name", "name"),)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_window: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict] = mapped_column(JSONB)


class InstitutionCode(Base):
    __tablename__ = "institution_codes"
    __table_args__ = (Index("idx_institution_codes_name", "name"),)

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_window: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_json: Mapped[dict] = mapped_column(JSONB)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text)
    business_registration_number: Mapped[str | None] = mapped_column(String(10), unique=True)
    region_code: Mapped[str | None] = mapped_column(Text)
    region_name: Mapped[str | None] = mapped_column(Text)
    company_size: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    industries: Mapped[list["CompanyIndustry"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    staff: Mapped["CompanyStaff | None"] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    staff_roles: Mapped[list["CompanyStaffRole"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    performances: Mapped[list["CompanyPerformance"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )
    certifications: Mapped[list["CompanyCertification"]] = relationship(
        back_populates="company", cascade="all, delete-orphan", passive_deletes=True
    )


class CompanyIndustry(Base):
    __tablename__ = "company_industries"

    company_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    industry_code: Mapped[str] = mapped_column(
        Text, ForeignKey("industry_codes.code"), primary_key=True
    )
    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Whether the company marked supporting evidence as held; not third-party verification.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    company: Mapped[Company] = relationship(back_populates="industries")
    industry: Mapped[IndustryCode] = relationship()


class CompanyStaff(Base):
    __tablename__ = "company_staff"

    company_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Whether the company marked supporting evidence as held; not third-party verification.",
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    company: Mapped[Company] = relationship(back_populates="staff")


class CompanyStaffRole(Base):
    __tablename__ = "company_staff_roles"
    __table_args__ = (
        CheckConstraint("career_years IS NULL OR career_years >= 0"),
    )

    company_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    role_name: Mapped[str] = mapped_column(Text, primary_key=True)
    headcount: Mapped[int] = mapped_column(Integer)
    career_years: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Whether the company marked supporting evidence as held; not third-party verification.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    company: Mapped[Company] = relationship(back_populates="staff_roles")


class CompanyPerformance(Base):
    __tablename__ = "company_performances"
    __table_args__ = (
        CheckConstraint("(completed_at IS NOT NULL) <> (completed_year IS NOT NULL)"),
        CheckConstraint("completed_year IS NULL OR completed_year BETWEEN 1900 AND 2100"),
        CheckConstraint("started_at IS NULL OR completed_at IS NULL OR started_at <= completed_at"),
        CheckConstraint(
            "started_at IS NULL OR completed_year IS NULL OR EXTRACT(YEAR FROM started_at) <= completed_year"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    client_name: Mapped[str | None] = mapped_column(Text)
    client_institution_code: Mapped[str | None] = mapped_column(
        Text, ForeignKey("institution_codes.code")
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 0))
    started_at: Mapped[date | None] = mapped_column(Date)
    completed_at: Mapped[date | None] = mapped_column(Date)
    completed_year: Mapped[int | None] = mapped_column(SmallInteger)
    description: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Whether the company marked supporting evidence as held; not third-party verification.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    company: Mapped[Company] = relationship(back_populates="performances")
    experience_fields: Mapped[list["CompanyPerformanceField"]] = relationship(
        back_populates="performance", cascade="all, delete-orphan", passive_deletes=True
    )


class CompanyPerformanceField(Base):
    __tablename__ = "company_performance_fields"

    performance_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("company_performances.id", ondelete="CASCADE"),
        primary_key=True,
    )
    field_name: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    performance: Mapped[CompanyPerformance] = relationship(back_populates="experience_fields")


class CompanyCertification(Base):
    __tablename__ = "company_certifications"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    certification_code: Mapped[str | None] = mapped_column(Text)
    certificate_number: Mapped[str | None] = mapped_column(Text)
    issuer_name: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[date | None] = mapped_column(Date)
    expires_at: Mapped[date | None] = mapped_column(Date)
    verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        comment="Whether the company marked supporting evidence as held; not third-party verification.",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    company: Mapped[Company] = relationship(back_populates="certifications")


Index(
    "idx_company_performances_company_completed",
    CompanyPerformance.company_id,
    CompanyPerformance.completed_at.desc(),
)
Index(
    "idx_company_certifications_company",
    CompanyCertification.company_id,
)


class BidNotice(Base):
    __tablename__ = "bid_notices"
    __table_args__ = (
        CheckConstraint("BTRIM(bid_notice_no) <> ''", name="bid_notices_no_not_blank"),
        CheckConstraint("BTRIM(title) <> ''", name="bid_notices_title_not_blank"),
        CheckConstraint(
            "business_type IN ('SERVICE', 'GOODS', 'CONSTRUCTION', 'FOREIGN', 'OTHER')",
            name="bid_notices_business_type_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    bid_notice_no: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    business_type: Mapped[str] = mapped_column(Text)
    notice_kind: Mapped[str | None] = mapped_column(Text)
    announcing_institution_code: Mapped[str | None] = mapped_column(Text)
    announcing_institution_name: Mapped[str | None] = mapped_column(Text)
    demanding_institution_code: Mapped[str | None] = mapped_column(Text)
    demanding_institution_name: Mapped[str | None] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    versions: Mapped[list["BidNoticeVersion"]] = relationship(
        back_populates="notice", cascade="all, delete-orphan", passive_deletes=True
    )


class BidNoticeVersion(Base):
    __tablename__ = "bid_notice_versions"
    __table_args__ = (
        UniqueConstraint("notice_id", "version_number", name="uq_notice_version_number"),
        UniqueConstraint("notice_id", "payload_hash", name="uq_notice_payload_hash"),
        UniqueConstraint("notice_id", "bid_notice_order", name="uq_notice_bid_order"),
        CheckConstraint("version_number > 0", name="bid_notice_versions_number_positive"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    notice_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bid_notices.id", ondelete="CASCADE")
    )
    version_number: Mapped[int] = mapped_column(Integer)
    bid_notice_order: Mapped[str] = mapped_column(Text)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    notice_kind: Mapped[str | None] = mapped_column(Text)
    registration_type: Mapped[str | None] = mapped_column(Text)
    is_reannouncement: Mapped[bool] = mapped_column(Boolean, default=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bid_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bid_closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allocated_budget: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    estimated_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 0))
    contract_method: Mapped[str | None] = mapped_column(Text)
    change_reason: Mapped[str | None] = mapped_column(Text)
    detail_url: Mapped[str | None] = mapped_column(Text)
    source_endpoint: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64))
    raw_json: Mapped[dict] = mapped_column(JSONB)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    notice: Mapped[BidNotice] = relationship(back_populates="versions")
    documents: Mapped[list["NoticeDocument"]] = relationship(
        back_populates="notice_version", cascade="all, delete-orphan", passive_deletes=True
    )


class NoticeRelation(Base):
    """Direct link from a reannouncement to its immediately previous notice."""

    __tablename__ = "notice_relations"
    __table_args__ = (
        CheckConstraint(
            "previous_notice_id IS NULL OR previous_notice_id <> notice_id",
            name="notice_relations_not_self_referential",
        ),
        CheckConstraint(
            "match_method IN ('API_FIELD', 'NAME_AGENCY_PRICE', 'MANUAL')",
            name="notice_relations_match_method_valid",
        ),
        CheckConstraint(
            "match_confidence IN ('CONFIRMED', 'SUGGESTED')",
            name="notice_relations_match_confidence_valid",
        ),
    )

    notice_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notices.id", ondelete="CASCADE"),
        primary_key=True,
    )
    previous_notice_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notices.id", ondelete="SET NULL"),
    )
    previous_bid_notice_no: Mapped[str] = mapped_column(Text)
    match_method: Mapped[str] = mapped_column(Text)
    match_confidence: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    notice: Mapped[BidNotice] = relationship(foreign_keys=[notice_id])
    previous_notice: Mapped[BidNotice | None] = relationship(foreign_keys=[previous_notice_id])


Index("idx_notice_relations_previous_notice", NoticeRelation.previous_notice_id)
Index("idx_notice_relations_previous_number", NoticeRelation.previous_bid_notice_no)


class NoticeFact(Base):
    """Normalized, version-scoped notice fact used for deterministic diffs."""

    __tablename__ = "notice_facts"
    __table_args__ = (
        UniqueConstraint(
            "notice_version_id", "fact_key", name="uq_notice_fact_version_key"
        ),
        CheckConstraint(
            "fact_key IN ('SUBMISSION_DEADLINE', 'BUDGET_AMOUNT', "
            "'ORDERING_AGENCY', 'JOINT_SUPPLY')",
            name="notice_facts_key_valid",
        ),
        CheckConstraint(
            "source_type IN ('G2B_API', 'DOCUMENT_EXTRACTION', 'MANUAL')",
            name="notice_facts_source_type_valid",
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
    fact_key: Mapped[str] = mapped_column(Text, nullable=False)
    value_json: Mapped[object] = mapped_column(JSONB, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_field: Mapped[str | None] = mapped_column(Text)
    raw_value: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("notice_documents.id", ondelete="SET NULL"),
    )
    evidence_location: Mapped[dict | None] = mapped_column(JSONB)
    quote: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


Index("idx_notice_facts_version", NoticeFact.notice_version_id)
Index("idx_notice_facts_key", NoticeFact.fact_key)


class NoticeChangeHistory(Base):
    """Raw field-level change history reported by the G2B API."""

    __tablename__ = "notice_change_histories"
    __table_args__ = (
        UniqueConstraint(
            "notice_id", "payload_hash", name="uq_notice_change_history_payload"
        ),
        CheckConstraint(
            "LENGTH(payload_hash) = 64",
            name="notice_change_histories_payload_hash_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    notice_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notices.id", ondelete="CASCADE"),
        nullable=False,
    )
    notice_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notice_versions.id", ondelete="SET NULL"),
    )
    bid_notice_order: Mapped[str | None] = mapped_column(Text)
    rebid_number: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_data_type: Mapped[str | None] = mapped_column(Text)
    item_name: Mapped[str] = mapped_column(Text, nullable=False)
    before_value: Mapped[str | None] = mapped_column(Text)
    after_value: Mapped[str | None] = mapped_column(Text)
    business_division_name: Mapped[str | None] = mapped_column(Text)
    source_endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


Index("idx_notice_change_histories_notice", NoticeChangeHistory.notice_id)
Index("idx_notice_change_histories_version", NoticeChangeHistory.notice_version_id)
Index("idx_notice_change_histories_changed_at", NoticeChangeHistory.changed_at.desc())


class NoticeDocument(Base):
    __tablename__ = "notice_documents"
    __table_args__ = (
        UniqueConstraint(
            "notice_version_id", "source_field", name="uq_notice_document_source"
        ),
        CheckConstraint("document_order >= 0", name="notice_documents_order_nonnegative"),
        CheckConstraint(
            "download_status IN ('PENDING', 'DOWNLOADED', 'FAILED')",
            name="notice_documents_download_status_valid",
        ),
        CheckConstraint(
            "extraction_status IN ('PENDING', 'EXTRACTED', 'EMPTY', 'UNSUPPORTED', 'FAILED')",
            name="notice_documents_extraction_status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    notice_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
    )
    document_order: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    source_field: Mapped[str] = mapped_column(Text)
    download_status: Mapped[str] = mapped_column(Text, default="PENDING")
    storage_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    file_sha256: Mapped[str | None] = mapped_column(String(64))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    download_error: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(Text, default="PENDING")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extracted_blocks: Mapped[list[dict] | None] = mapped_column(JSONB)
    extracted_char_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text_sha256: Mapped[str | None] = mapped_column(String(64))
    text_extractor: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    notice_version: Mapped[BidNoticeVersion] = relationship(back_populates="documents")

    @property
    def viewer_type(self) -> str:
        name = self.name.lower()
        if self.content_type == "application/pdf" or name.endswith(".pdf"):
            return "PDF"
        if (
            name.endswith((".hwp", ".hwpx"))
            or (self.text_extractor or "").startswith("HWP")
        ):
            return "RHWP"
        return "DOWNLOAD"

    @property
    def render_source_url(self) -> str:
        version = self.notice_version
        return (
            f"/api/v1/notices/{version.notice_id}/versions/{version.version_number}"
            f"/documents/{self.id}/source"
        )

    @property
    def text_url(self) -> str:
        version = self.notice_version
        return (
            f"/api/v1/notices/{version.notice_id}/versions/{version.version_number}"
            f"/documents/{self.id}/text"
        )

    @property
    def preview_url(self) -> str | None:
        if self.viewer_type != "PDF":
            return None
        version = self.notice_version
        return (
            f"/api/v1/notices/{version.notice_id}/versions/{version.version_number}"
            f"/documents/{self.id}/preview"
        )


class NoticeCollectionRun(Base):
    __tablename__ = "notice_collection_runs"
    __table_args__ = (
        CheckConstraint(
            "business_type IN ('SERVICE', 'GOODS', 'CONSTRUCTION', 'FOREIGN', 'OTHER')",
            name="notice_collection_runs_business_type_valid",
        ),
        CheckConstraint(
            "inquiry_type IN ('REGISTERED', 'CHANGED', 'NOTICE_NUMBER')",
            name="notice_collection_runs_inquiry_type_valid",
        ),
        CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED')",
            name="notice_collection_runs_status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    business_type: Mapped[str] = mapped_column(Text)
    inquiry_type: Mapped[str] = mapped_column(Text)
    window_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    window_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text)
    api_calls: Mapped[int] = mapped_column(Integer, default=0)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    new_version_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_item_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NoticeHistoryBackfillJob(Base):
    """Durable request to fetch every published order for one G2B notice."""

    __tablename__ = "notice_history_backfill_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="notice_history_backfill_jobs_status_valid",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="notice_history_backfill_jobs_attempts_nonnegative",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    notice_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("bid_notices.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(Text, default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )


Index(
    "idx_notice_history_backfill_jobs_due",
    NoticeHistoryBackfillJob.status,
    NoticeHistoryBackfillJob.next_attempt_at,
)


class PreflightCase(Base):
    __tablename__ = "preflight_cases"
    __table_args__ = (
        CheckConstraint("BTRIM(title) <> ''", name="preflight_cases_title_not_blank"),
        CheckConstraint(
            "status IN ('DRAFT', 'READY', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="preflight_cases_status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    company_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("companies.id", ondelete="SET NULL")
    )
    notice_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bid_notices.id", ondelete="CASCADE")
    )
    baseline_version_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bid_notice_versions.id", ondelete="CASCADE")
    )
    current_version_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("bid_notice_versions.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    documents: Mapped[list["ProposalDocument"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", passive_deletes=True
    )


class ProposalDocument(Base):
    __tablename__ = "proposal_documents"
    __table_args__ = (
        UniqueConstraint("case_id", "file_sha256", name="uq_proposal_document_hash"),
        UniqueConstraint("case_id", "document_order", name="uq_proposal_document_order"),
        CheckConstraint("document_order >= 0", name="proposal_documents_order_nonnegative"),
        CheckConstraint(
            "role IN ('PROPOSAL', 'ATTACHMENT')", name="proposal_documents_role_valid"
        ),
        CheckConstraint(
            "storage_status IN ('STORED', 'FAILED')",
            name="proposal_documents_storage_status_valid",
        ),
        CheckConstraint(
            "extraction_status IN ('PENDING', 'EXTRACTED', 'EMPTY', 'UNSUPPORTED', 'FAILED')",
            name="proposal_documents_extraction_status_valid",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    case_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("preflight_cases.id", ondelete="CASCADE")
    )
    document_order: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(Text, default="PROPOSAL")
    name: Mapped[str] = mapped_column(Text)
    storage_status: Mapped[str] = mapped_column(Text, default="STORED")
    storage_key: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger)
    file_sha256: Mapped[str] = mapped_column(String(64))
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    storage_error: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(Text, default="PENDING")
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extracted_blocks: Mapped[list[dict] | None] = mapped_column(JSONB)
    extracted_char_count: Mapped[int | None] = mapped_column(Integer)
    extracted_text_sha256: Mapped[str | None] = mapped_column(String(64))
    text_extractor: Mapped[str | None] = mapped_column(Text)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extraction_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    case: Mapped[PreflightCase] = relationship(back_populates="documents")

    @property
    def viewer_type(self) -> str:
        name = self.name.lower()
        if self.content_type == "application/pdf" or name.endswith(".pdf"):
            return "PDF"
        if name.endswith((".hwp", ".hwpx")) or (self.text_extractor or "").startswith("HWP"):
            return "RHWP"
        return "DOWNLOAD"

    @property
    def render_source_url(self) -> str:
        return f"/api/v1/preflight-cases/{self.case_id}/documents/{self.id}/source"

    @property
    def text_url(self) -> str:
        return f"/api/v1/preflight-cases/{self.case_id}/documents/{self.id}/text"

    @property
    def preview_url(self) -> str | None:
        return (
            f"/api/v1/preflight-cases/{self.case_id}/documents/{self.id}/preview"
            if self.viewer_type == "PDF"
            else None
        )


Index("idx_bid_notices_title", BidNotice.title)
Index("idx_bid_notices_last_seen", BidNotice.last_seen_at.desc())
Index("idx_bid_notices_business_type", BidNotice.business_type, BidNotice.last_seen_at)
Index(
    "uq_bid_notice_versions_current",
    BidNoticeVersion.notice_id,
    unique=True,
    postgresql_where=text("is_current"),
)
Index(
    "idx_bid_notice_versions_notice_created",
    BidNoticeVersion.notice_id,
    BidNoticeVersion.version_number.desc(),
)
Index("idx_notice_collection_runs_started", NoticeCollectionRun.started_at.desc())
Index("idx_preflight_cases_notice", PreflightCase.notice_id, PreflightCase.created_at)
Index("idx_preflight_cases_company", PreflightCase.company_id, PreflightCase.created_at)
Index("idx_proposal_documents_case", ProposalDocument.case_id, ProposalDocument.document_order)
