"""Human relevance reviews with independent approval and immutable audit events.

Revision ID: 027_relevance_review_labels
Revises: 026_core_requirement_status
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "027_relevance_review_labels"
down_revision = "026_core_requirement_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "relevance_review_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("notice_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bid_notice_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("grade", sa.SmallInteger(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("subject_origin", sa.Text(), nullable=False),
        sa.Column("company_fingerprint", sa.String(64), nullable=False),
        sa.Column("notice_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reviewer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="RESTRICT")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("grade BETWEEN 0 AND 3", name="relevance_review_grade_valid"),
        sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'REOPENED')", name="relevance_review_status_valid"),
        sa.CheckConstraint("subject_origin IN ('REAL', 'SYNTHETIC', 'UNKNOWN')", name="relevance_review_origin_valid"),
        sa.UniqueConstraint("company_id", "notice_version_id", name="uq_relevance_review_pair"),
    )
    op.create_index("idx_relevance_review_status", "relevance_review_labels", ["status", sa.text("reviewed_at DESC")])
    op.create_table(
        "relevance_review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("label_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("relevance_review_labels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before_state", postgresql.JSONB()),
        sa.Column("after_state", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    # Dropping approved human work is never an implicit rollback operation.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM relevance_review_labels LIMIT 1) THEN
            RAISE EXCEPTION 'Cannot downgrade while human relevance reviews exist';
        END IF;
    END $$""")
    op.drop_table("relevance_review_events")
    op.drop_index("idx_relevance_review_status", table_name="relevance_review_labels")
    op.drop_table("relevance_review_labels")
