from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanySize(StrEnum):
    MICRO = "MICRO"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    MID_SIZED = "MID_SIZED"
    LARGE = "LARGE"
    NONE = "NONE"


class MasterCodeType(StrEnum):
    INDUSTRIES = "industries"
    PRODUCTS = "products"
    INSTITUTIONS = "institutions"


class BusinessType(StrEnum):
    SERVICE = "SERVICE"
    GOODS = "GOODS"
    CONSTRUCTION = "CONSTRUCTION"
    FOREIGN = "FOREIGN"
    OTHER = "OTHER"


class NoticeInquiryType(StrEnum):
    REGISTERED = "REGISTERED"
    CHANGED = "CHANGED"
    NOTICE_NUMBER = "NOTICE_NUMBER"


class ProposalDocumentRole(StrEnum):
    PROPOSAL = "PROPOSAL"
    ATTACHMENT = "ATTACHMENT"


def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("must not be blank")
    return value


def _unique_stripped(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _strip_required(value)
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


class StaffRoleInput(ApiModel):
    role_name: str
    headcount: int = Field(ge=0)
    career_years: float | None = Field(default=None, ge=0, le=999.99)
    verified: bool = False

    @field_validator("role_name")
    @classmethod
    def validate_role_name(cls, value: str) -> str:
        return _strip_required(value)


class StaffCreate(ApiModel):
    total_count: int = Field(ge=0)
    verified: bool = False
    roles: list[StaffRoleInput] = Field(default_factory=list)

    @field_validator("roles")
    @classmethod
    def validate_unique_roles(cls, values: list[StaffRoleInput]) -> list[StaffRoleInput]:
        names = [value.role_name for value in values]
        if len(names) != len(set(names)):
            raise ValueError("role_name must be unique")
        return values


class StaffUpdate(ApiModel):
    total_count: int | None = Field(default=None, ge=0)
    verified: bool | None = None
    roles: list[StaffRoleInput] | None = None

    @field_validator("roles")
    @classmethod
    def validate_unique_roles(
        cls, values: list[StaffRoleInput] | None
    ) -> list[StaffRoleInput] | None:
        if values is None:
            return values
        names = [value.role_name for value in values]
        if len(names) != len(set(names)):
            raise ValueError("role_name must be unique")
        return values


class CompanyCreate(ApiModel):
    name: str
    business_registration_number: str | None = None
    region_code: str
    region_name: str | None = None
    company_size: CompanySize
    industry_codes: list[str] = Field(min_length=1)
    staff: StaffCreate

    @field_validator("name", "region_code")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("region_name")
    @classmethod
    def strip_region_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("business_registration_number", mode="before")
    @classmethod
    def normalize_business_number(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        digits = "".join(character for character in str(value) if character.isdigit())
        if len(digits) != 10:
            raise ValueError("business_registration_number must contain 10 digits")
        return digits

    @field_validator("industry_codes")
    @classmethod
    def validate_industry_codes(cls, values: list[str]) -> list[str]:
        return _unique_stripped(values)


class CompanyUpdate(ApiModel):
    name: str | None = None
    business_registration_number: str | None = None
    region_code: str | None = None
    region_name: str | None = None
    company_size: CompanySize | None = None
    industry_codes: list[str] | None = None
    staff: StaffUpdate | None = None

    @field_validator("name", "region_code")
    @classmethod
    def validate_optional_required_text(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("region_name")
    @classmethod
    def strip_region_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("business_registration_number", mode="before")
    @classmethod
    def normalize_business_number(cls, value: str | None) -> str | None:
        if value is None or not str(value).strip():
            return None
        digits = "".join(character for character in str(value) if character.isdigit())
        if len(digits) != 10:
            raise ValueError("business_registration_number must contain 10 digits")
        return digits

    @field_validator("industry_codes")
    @classmethod
    def validate_industry_codes(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return values
        values = _unique_stripped(values)
        if not values:
            raise ValueError("industry_codes must contain at least one code")
        return values


class PerformanceCreate(ApiModel):
    name: str
    client_name: str | None = None
    client_institution_code: str | None = None
    amount: int = Field(ge=0, le=999_999_999_999_999_999)
    started_at: date | None = None
    completed_at: date | None = None
    completed_year: int | None = Field(default=None, ge=1900, le=2100)
    description: str | None = None
    fields: list[str] = Field(default_factory=list)
    verified: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("client_name", "client_institution_code", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, values: list[str]) -> list[str]:
        return _unique_stripped(values)

    @model_validator(mode="after")
    def validate_dates(self) -> "PerformanceCreate":
        if (self.completed_at is None) == (self.completed_year is None):
            raise ValueError("exactly one of completed_at or completed_year is required")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.started_at > self.completed_at
        ):
            raise ValueError("started_at must be on or before completed_at")
        if (
            self.started_at is not None
            and self.completed_year is not None
            and self.started_at.year > self.completed_year
        ):
            raise ValueError("started_at year must be on or before completed_year")
        return self


class PerformanceUpdate(ApiModel):
    name: str | None = None
    client_name: str | None = None
    client_institution_code: str | None = None
    amount: int | None = Field(default=None, ge=0, le=999_999_999_999_999_999)
    started_at: date | None = None
    completed_at: date | None = None
    completed_year: int | None = Field(default=None, ge=1900, le=2100)
    description: str | None = None
    fields: list[str] | None = None
    verified: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("client_name", "client_institution_code", "description")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, values: list[str] | None) -> list[str] | None:
        return _unique_stripped(values) if values is not None else None


class CertificationCreate(ApiModel):
    name: str
    certification_code: str | None = None
    certificate_number: str | None = None
    issuer_name: str | None = None
    issued_at: date | None = None
    expires_at: date | None = None
    verified: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("certificate_number", "issuer_name")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("certification_code")
    @classmethod
    def normalize_certification_code(cls, value: str | None) -> str | None:
        return value.strip().upper() or None if value is not None else None

    @model_validator(mode="after")
    def validate_dates(self) -> "CertificationCreate":
        if self.issued_at and self.expires_at and self.issued_at > self.expires_at:
            raise ValueError("issued_at must be on or before expires_at")
        return self


class CertificationUpdate(ApiModel):
    name: str | None = None
    certification_code: str | None = None
    certificate_number: str | None = None
    issuer_name: str | None = None
    issued_at: date | None = None
    expires_at: date | None = None
    verified: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("certificate_number", "issuer_name")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("certification_code")
    @classmethod
    def normalize_certification_code(cls, value: str | None) -> str | None:
        return value.strip().upper() or None if value is not None else None


class IndustryRead(ApiModel):
    code: str
    name: str
    verified: bool


class StaffRoleRead(ApiModel):
    role_name: str
    headcount: int
    career_years: float | None
    verified: bool


class StaffRead(ApiModel):
    total_count: int
    verified: bool
    roles: list[StaffRoleRead]


class PerformanceRead(ApiModel):
    id: UUID
    name: str
    client_name: str | None
    client_institution_code: str | None
    amount: int
    started_at: date | None
    completed_at: date | None
    completed_year: int | None
    description: str | None
    fields: list[str]
    verified: bool
    created_at: datetime
    updated_at: datetime


class CertificationRead(ApiModel):
    id: UUID
    name: str
    certification_code: str | None
    certificate_number: str | None
    issuer_name: str | None
    issued_at: date | None
    expires_at: date | None
    verified: bool
    created_at: datetime
    updated_at: datetime


class CompanyRead(ApiModel):
    id: UUID
    name: str
    business_registration_number: str | None
    region_code: str | None
    region_name: str | None
    company_size: CompanySize
    industries: list[IndustryRead]
    staff: StaffRead | None
    performances: list[PerformanceRead]
    certifications: list[CertificationRead]
    created_at: datetime
    updated_at: datetime


class MasterCodeRead(ApiModel):
    code: str
    name: str
    active: bool


class MasterCodeSearchResponse(ApiModel):
    type: MasterCodeType
    query: str | None
    active_only: bool
    total: int
    limit: int
    offset: int
    items: list[MasterCodeRead]


class NoticeDocumentRead(ApiModel):
    id: UUID
    document_order: int
    name: str
    url: str
    source_field: str
    download_status: str
    storage_key: str | None
    content_type: str | None
    file_size_bytes: int | None
    file_sha256: str | None
    downloaded_at: datetime | None
    download_error: str | None
    extraction_status: str
    extracted_char_count: int | None
    extracted_text_sha256: str | None
    text_extractor: str | None
    extracted_at: datetime | None
    extraction_error: str | None
    viewer_type: str
    render_source_url: str
    text_url: str
    preview_url: str | None


class NoticeDocumentTextRead(ApiModel):
    document_id: UUID
    name: str
    extraction_status: str
    extractor: str | None
    char_count: int | None
    text_sha256: str | None
    text: str | None
    blocks: list[dict] | None


class DocumentExtractionBatchRead(ApiModel):
    requested_count: int
    extracted_count: int
    empty_count: int
    unsupported_count: int
    failed_count: int


class PreflightCaseCreate(ApiModel):
    notice_id: UUID
    company_id: UUID | None = None
    baseline_version_number: int | None = Field(default=None, ge=1)
    current_version_number: int | None = Field(default=None, ge=1)
    title: str | None = None

    @field_validator("title")
    @classmethod
    def strip_case_title(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None


class ProposalDocumentRead(ApiModel):
    id: UUID
    case_id: UUID
    document_order: int
    role: ProposalDocumentRole
    name: str
    storage_status: str
    content_type: str | None
    file_size_bytes: int
    file_sha256: str
    stored_at: datetime
    extraction_status: str
    extracted_char_count: int | None
    extracted_text_sha256: str | None
    text_extractor: str | None
    extracted_at: datetime | None
    extraction_error: str | None
    viewer_type: str
    render_source_url: str
    text_url: str
    preview_url: str | None


class PreflightCaseRead(ApiModel):
    id: UUID
    company_id: UUID | None
    notice_id: UUID
    bid_notice_no: str
    notice_title: str
    title: str
    status: str
    baseline_version_id: UUID | None
    baseline_version_number: int | None
    current_version_id: UUID
    current_version_number: int
    documents: list[ProposalDocumentRead]
    created_at: datetime
    updated_at: datetime


class PreflightCaseSearchResponse(ApiModel):
    total: int
    limit: int
    offset: int
    items: list[PreflightCaseRead]


class BidNoticeVersionRead(ApiModel):
    id: UUID
    version_number: int
    bid_notice_order: str
    is_current: bool
    notice_kind: str | None
    registration_type: str | None
    is_reannouncement: bool
    posted_at: datetime | None
    changed_at: datetime | None
    bid_started_at: datetime | None
    bid_closed_at: datetime | None
    opened_at: datetime | None
    allocated_budget: int | None
    estimated_price: int | None
    contract_method: str | None
    change_reason: str | None
    detail_url: str | None
    source_endpoint: str
    payload_hash: str
    collected_at: datetime
    documents: list[NoticeDocumentRead]


class BidNoticeSummary(ApiModel):
    id: UUID
    bid_notice_no: str
    title: str
    business_type: BusinessType
    notice_kind: str | None
    announcing_institution_code: str | None
    announcing_institution_name: str | None
    demanding_institution_code: str | None
    demanding_institution_name: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    current_version: int


class NoticeRelationRead(ApiModel):
    notice_id: UUID
    previous_notice_id: UUID | None
    previous_bid_notice_no: str
    previous_notice_title: str | None
    match_method: str
    match_confidence: str
    resolved: bool
    created_at: datetime
    updated_at: datetime


class NoticeFactRead(ApiModel):
    id: UUID
    notice_version_id: UUID
    fact_key: str
    value_json: object
    source_type: str
    source_field: str | None
    raw_value: str | None
    document_id: UUID | None
    evidence_location: dict | None
    quote: str | None
    created_at: datetime
    updated_at: datetime


class NoticeFactChangeRead(ApiModel):
    fact_key: str
    change_type: str
    baseline: NoticeFactRead | None
    current: NoticeFactRead | None


class NoticeFactDiffRead(ApiModel):
    baseline_version_id: UUID
    current_version_id: UUID
    changes: list[NoticeFactChangeRead]


class NoticeChangeHistoryRead(ApiModel):
    id: UUID
    notice_id: UUID
    notice_version_id: UUID | None
    bid_notice_order: str | None
    rebid_number: str | None
    changed_at: datetime | None
    change_data_type: str | None
    item_name: str
    before_value: str | None
    after_value: str | None
    business_division_name: str | None
    source_endpoint: str
    payload_hash: str
    collected_at: datetime
    created_at: datetime
    updated_at: datetime


class BidNoticeDetail(BidNoticeSummary):
    latest: BidNoticeVersionRead
    relation: NoticeRelationRead | None = None


class BidNoticeSearchResponse(ApiModel):
    query: str | None
    business_type: BusinessType | None
    total: int
    limit: int
    offset: int
    items: list[BidNoticeSummary]


class NoticeSyncRequest(ApiModel):
    business_type: BusinessType
    inquiry_type: NoticeInquiryType = NoticeInquiryType.REGISTERED
    window_started_at: datetime | None = None
    window_ended_at: datetime | None = None
    bid_notice_no: str | None = None
    page_size: int = Field(default=100, ge=1, le=999)
    max_pages: int = Field(default=10, ge=1, le=100)

    @field_validator("bid_notice_no")
    @classmethod
    def strip_bid_notice_no(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def validate_scope(self) -> "NoticeSyncRequest":
        if self.inquiry_type == NoticeInquiryType.NOTICE_NUMBER:
            if self.bid_notice_no is None:
                raise ValueError("bid_notice_no is required for NOTICE_NUMBER")
            return self
        if self.window_started_at is None or self.window_ended_at is None:
            raise ValueError("window_started_at and window_ended_at are required")
        if self.window_started_at > self.window_ended_at:
            raise ValueError("window_started_at must be on or before window_ended_at")
        if (self.window_ended_at - self.window_started_at).days > 31:
            raise ValueError("collection window must not exceed 31 days")
        return self


class NoticeCollectionRunRead(ApiModel):
    id: UUID
    business_type: BusinessType
    inquiry_type: NoticeInquiryType
    window_started_at: datetime | None
    window_ended_at: datetime | None
    status: str
    api_calls: int
    fetched_count: int
    created_count: int
    new_version_count: int
    unchanged_count: int
    failed_item_count: int
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None


class ErrorBody(ApiModel):
    code: str
    message: str
    details: object | None = None


class ErrorResponse(ApiModel):
    error: ErrorBody
