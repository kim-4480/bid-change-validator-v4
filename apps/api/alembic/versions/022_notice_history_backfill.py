"""Add durable notice-history backfill jobs and item failure accounting."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "022_notice_history_backfill"
down_revision = "021_user_company"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notice_collection_runs",
        sa.Column(
            "failed_item_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_unique_constraint(
        "uq_notice_bid_order",
        "bid_notice_versions",
        ["notice_id", "bid_notice_order"],
    )
    op.create_table(
        "notice_history_backfill_jobs",
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
            unique=True,
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name="notice_history_backfill_jobs_status_valid",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="notice_history_backfill_jobs_attempts_nonnegative",
        ),
    )
    op.create_index(
        "idx_notice_history_backfill_jobs_due",
        "notice_history_backfill_jobs",
        ["status", "next_attempt_at"],
    )
    op.execute("ALTER TABLE notice_history_backfill_jobs ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bidcheck_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON notice_history_backfill_jobs TO bidcheck_app;
                CREATE POLICY notice_history_backfill_backend_access
                    ON notice_history_backfill_jobs
                    FOR ALL TO bidcheck_app
                    USING (true) WITH CHECK (true);
            END IF;
        END
        $$
        """
    )

    # Existing notices need the same one-time full-history audit as newly found
    # notices. The worker consumes this queue gradually after deployment.
    op.execute(
        """
        INSERT INTO notice_history_backfill_jobs (notice_id, status)
        SELECT id, 'PENDING' FROM bid_notices
        ON CONFLICT (notice_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(
        "idx_notice_history_backfill_jobs_due",
        table_name="notice_history_backfill_jobs",
    )
    op.drop_table("notice_history_backfill_jobs")
    op.drop_constraint(
        "uq_notice_bid_order",
        "bid_notice_versions",
        type_="unique",
    )
    op.drop_column("notice_collection_runs", "failed_item_count")
