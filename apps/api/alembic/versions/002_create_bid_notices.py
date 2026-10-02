"""Create bid notice collection and version tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "002_bid_notices"
down_revision = "001_company_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bid_notices",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("bid_notice_no", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("business_type", sa.Text(), nullable=False),
        sa.Column("notice_kind", sa.Text()),
        sa.Column("announcing_institution_code", sa.Text()),
        sa.Column("announcing_institution_name", sa.Text()),
        sa.Column("demanding_institution_code", sa.Text()),
        sa.Column("demanding_institution_name", sa.Text()),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("BTRIM(bid_notice_no) <> ''", name="bid_notices_no_not_blank"),
        sa.CheckConstraint("BTRIM(title) <> ''", name="bid_notices_title_not_blank"),
        sa.CheckConstraint(
            "business_type IN ('SERVICE', 'GOODS', 'CONSTRUCTION', 'FOREIGN', 'OTHER')",
            name="bid_notices_business_type_valid",
        ),
    )
    op.create_index("idx_bid_notices_title", "bid_notices", ["title"])
    op.create_index("idx_bid_notices_last_seen", "bid_notices", [sa.text("last_seen_at DESC")])
    op.create_index(
        "idx_bid_notices_business_type", "bid_notices", ["business_type", "last_seen_at"]
    )

    op.create_table(
        "bid_notice_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "notice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("bid_notice_order", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notice_kind", sa.Text()),
        sa.Column("registration_type", sa.Text()),
        sa.Column("is_reannouncement", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("posted_at", sa.DateTime(timezone=True)),
        sa.Column("changed_at", sa.DateTime(timezone=True)),
        sa.Column("bid_started_at", sa.DateTime(timezone=True)),
        sa.Column("bid_closed_at", sa.DateTime(timezone=True)),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("allocated_budget", sa.Numeric(18, 0)),
        sa.Column("estimated_price", sa.Numeric(18, 0)),
        sa.Column("contract_method", sa.Text()),
        sa.Column("change_reason", sa.Text()),
        sa.Column("detail_url", sa.Text()),
        sa.Column("source_endpoint", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "raw_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint("notice_id", "version_number", name="uq_notice_version_number"),
        sa.UniqueConstraint("notice_id", "payload_hash", name="uq_notice_payload_hash"),
        sa.CheckConstraint("version_number > 0", name="bid_notice_versions_number_positive"),
    )
    op.create_index(
        "uq_bid_notice_versions_current",
        "bid_notice_versions",
        ["notice_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_index(
        "idx_bid_notice_versions_notice_created",
        "bid_notice_versions",
        ["notice_id", sa.text("version_number DESC")],
    )

    op.create_table(
        "notice_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "notice_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("source_field", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.UniqueConstraint(
            "notice_version_id", "source_field", name="uq_notice_document_source"
        ),
        sa.CheckConstraint("document_order >= 0", name="notice_documents_order_nonnegative"),
    )

    op.create_table(
        "notice_collection_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("business_type", sa.Text(), nullable=False),
        sa.Column("inquiry_type", sa.Text(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True)),
        sa.Column("window_ended_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("api_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_version_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unchanged_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "business_type IN ('SERVICE', 'GOODS', 'CONSTRUCTION', 'FOREIGN', 'OTHER')",
            name="notice_collection_runs_business_type_valid",
        ),
        sa.CheckConstraint(
            "inquiry_type IN ('REGISTERED', 'CHANGED', 'NOTICE_NUMBER')",
            name="notice_collection_runs_inquiry_type_valid",
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'FAILED')",
            name="notice_collection_runs_status_valid",
        ),
    )
    op.create_index(
        "idx_notice_collection_runs_started",
        "notice_collection_runs",
        [sa.text("started_at DESC")],
    )

    op.execute(
        """
        CREATE TRIGGER bid_notices_set_updated_at
        BEFORE UPDATE ON bid_notices
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.drop_index("idx_notice_collection_runs_started", table_name="notice_collection_runs")
    op.drop_table("notice_collection_runs")
    op.drop_table("notice_documents")
    op.drop_index(
        "idx_bid_notice_versions_notice_created", table_name="bid_notice_versions"
    )
    op.drop_index("uq_bid_notice_versions_current", table_name="bid_notice_versions")
    op.drop_table("bid_notice_versions")
    op.drop_index("idx_bid_notices_business_type", table_name="bid_notices")
    op.drop_index("idx_bid_notices_last_seen", table_name="bid_notices")
    op.drop_index("idx_bid_notices_title", table_name="bid_notices")
    op.drop_table("bid_notices")
