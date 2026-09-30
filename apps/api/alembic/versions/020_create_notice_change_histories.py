"""Create authoritative G2B notice change-history storage."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "020_notice_change_histories"
down_revision = "019_auth_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notice_change_histories",
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
        sa.Column(
            "notice_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notice_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("bid_notice_order", sa.Text()),
        sa.Column("rebid_number", sa.Text()),
        sa.Column("changed_at", sa.DateTime(timezone=True)),
        sa.Column("change_data_type", sa.Text()),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("before_value", sa.Text()),
        sa.Column("after_value", sa.Text()),
        sa.Column("business_division_name", sa.Text()),
        sa.Column("source_endpoint", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "notice_id", "payload_hash", name="uq_notice_change_history_payload"
        ),
        sa.CheckConstraint(
            "LENGTH(payload_hash) = 64",
            name="notice_change_histories_payload_hash_length",
        ),
    )
    op.create_index(
        "idx_notice_change_histories_notice",
        "notice_change_histories",
        ["notice_id"],
    )
    op.create_index(
        "idx_notice_change_histories_version",
        "notice_change_histories",
        ["notice_version_id"],
    )
    op.create_index(
        "idx_notice_change_histories_changed_at",
        "notice_change_histories",
        [sa.text("changed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_notice_change_histories_changed_at",
        table_name="notice_change_histories",
    )
    op.drop_index(
        "idx_notice_change_histories_version",
        table_name="notice_change_histories",
    )
    op.drop_index(
        "idx_notice_change_histories_notice",
        table_name="notice_change_histories",
    )
    op.drop_table("notice_change_histories")
