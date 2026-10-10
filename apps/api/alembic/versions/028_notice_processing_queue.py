"""Durable, version-scoped post-collection processing jobs.

Revision ID: 028_notice_processing_queue
Revises: 027_relevance_review_labels
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "028_notice_processing_queue"
down_revision = "027_relevance_review_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notice_processing_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("notice_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_budget", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="RESTRICT")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("notice_version_id", "stage", "input_fingerprint", name="uq_notice_processing_input"),
        sa.CheckConstraint("stage IN ('EXTRACT', 'INDEX', 'FEATURES', 'ANALYZE')", name="notice_processing_stage_valid"),
        sa.CheckConstraint("status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'SUPERSEDED')", name="notice_processing_status_valid"),
        sa.CheckConstraint("attempts >= 0", name="notice_processing_attempts_nonnegative"),
    )
    op.create_index("idx_notice_processing_due", "notice_processing_jobs", ["status", "next_attempt_at", "priority"])
    op.create_table(
        "notice_processing_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notice_processing_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_notice_processing_attempt_job", "notice_processing_attempts", ["job_id", "attempt_number"])
    op.create_table(
        "notice_recommendation_features",
        sa.Column("notice_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    # Processing and human approvals are audit history, not disposable cache.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM notice_processing_jobs LIMIT 1) THEN
            RAISE EXCEPTION 'Cannot downgrade while processing job history exists';
        END IF;
    END $$""")
    op.drop_table("notice_recommendation_features")
    op.drop_index("idx_notice_processing_attempt_job", table_name="notice_processing_attempts")
    op.drop_table("notice_processing_attempts")
    op.drop_index("idx_notice_processing_due", table_name="notice_processing_jobs")
    op.drop_table("notice_processing_jobs")
