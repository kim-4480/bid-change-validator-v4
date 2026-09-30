"""Create preflight cases and proposal document storage."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "005_preflight_cases"
down_revision = "004_document_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "preflight_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "notice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "baseline_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "current_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="DRAFT"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("BTRIM(title) <> ''", name="preflight_cases_title_not_blank"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'READY', 'PROCESSING', 'COMPLETED', 'FAILED')",
            name="preflight_cases_status_valid",
        ),
    )
    op.create_index("idx_preflight_cases_notice", "preflight_cases", ["notice_id", "created_at"])
    op.create_index("idx_preflight_cases_company", "preflight_cases", ["company_id", "created_at"])

    op.create_table(
        "proposal_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "case_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("preflight_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_order", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False, server_default="PROPOSAL"),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("storage_status", sa.Text(), nullable=False, server_default="STORED"),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text()),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("storage_error", sa.Text()),
        sa.Column("extraction_status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("extracted_blocks", postgresql.JSONB()),
        sa.Column("extracted_char_count", sa.Integer()),
        sa.Column("extracted_text_sha256", sa.String(64)),
        sa.Column("text_extractor", sa.Text()),
        sa.Column("extracted_at", sa.DateTime(timezone=True)),
        sa.Column("extraction_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("case_id", "file_sha256", name="uq_proposal_document_hash"),
        sa.UniqueConstraint("case_id", "document_order", name="uq_proposal_document_order"),
        sa.CheckConstraint("document_order >= 0", name="proposal_documents_order_nonnegative"),
        sa.CheckConstraint(
            "role IN ('PROPOSAL', 'ATTACHMENT')",
            name="proposal_documents_role_valid",
        ),
        sa.CheckConstraint(
            "storage_status IN ('STORED', 'FAILED')",
            name="proposal_documents_storage_status_valid",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('PENDING', 'EXTRACTED', 'EMPTY', 'UNSUPPORTED', 'FAILED')",
            name="proposal_documents_extraction_status_valid",
        ),
    )
    op.create_index("idx_proposal_documents_case", "proposal_documents", ["case_id", "document_order"])

    op.execute(
        """
        CREATE TRIGGER preflight_cases_set_updated_at
        BEFORE UPDATE ON preflight_cases
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.drop_index("idx_proposal_documents_case", table_name="proposal_documents")
    op.drop_table("proposal_documents")
    op.drop_index("idx_preflight_cases_company", table_name="preflight_cases")
    op.drop_index("idx_preflight_cases_notice", table_name="preflight_cases")
    op.drop_table("preflight_cases")
