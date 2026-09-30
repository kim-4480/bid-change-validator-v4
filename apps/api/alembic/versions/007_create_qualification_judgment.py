"""Persist profile completeness and deterministic qualification judgments."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "007_qualification_judgment"
down_revision = "006_qualification_analysis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_qualification_profile_completeness",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("region_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("company_size_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("industries_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("staff_total_complete", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("staff_roles_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("performances_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("certifications_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "qualification_judgment_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("preflight_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("preflight_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("analysis_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("notice_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("overall_status", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("profile_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("analysis_status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("overall_status IN ('eligible', 'ineligible', 'insufficient_data')", name="qualification_judgment_runs_overall_status_valid"),
    )
    op.create_index("idx_qualification_judgment_runs_case_created", "qualification_judgment_runs", ["preflight_case_id", "created_at"])
    op.create_index("idx_qualification_judgment_runs_analysis", "qualification_judgment_runs", ["analysis_run_id"])

    op.create_table(
        "qualification_judgments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("judgment_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("judgment_key", sa.Text(), nullable=False),
        sa.Column("requirement_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("basis_type", sa.Text(), nullable=False),
        sa.Column("evidence_held", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("requires_evidence", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("profile_refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("requirement_evidence_keys", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rule_version", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("judgment_run_id", "requirement_key", name="uq_qualification_judgment_run_requirement"),
        sa.CheckConstraint("status IN ('SATISFIED', 'UNSATISFIED', 'UNKNOWN')", name="qualification_judgments_status_valid"),
        sa.CheckConstraint("basis_type IN ('PROFILE', 'USER_ANSWER', 'NONE')", name="qualification_judgments_basis_type_valid"),
        sa.CheckConstraint("reason_code IN ('RULE_MATCH', 'RULE_MISMATCH', 'INSUFFICIENT_DATA', 'NEEDS_REVIEW', 'UNSUPPORTED_REQUIREMENT')", name="qualification_judgments_reason_code_valid"),
    )
    op.create_index("idx_qualification_judgments_run_status", "qualification_judgments", ["judgment_run_id", "status"])

    op.execute("""
        CREATE TRIGGER company_qualification_profile_completeness_set_updated_at
        BEFORE UPDATE ON company_qualification_profile_completeness
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)


def downgrade() -> None:
    op.drop_index("idx_qualification_judgments_run_status", table_name="qualification_judgments")
    op.drop_table("qualification_judgments")
    op.drop_index("idx_qualification_judgment_runs_analysis", table_name="qualification_judgment_runs")
    op.drop_index("idx_qualification_judgment_runs_case_created", table_name="qualification_judgment_runs")
    op.drop_table("qualification_judgment_runs")
    op.execute("DROP TRIGGER IF EXISTS company_qualification_profile_completeness_set_updated_at ON company_qualification_profile_completeness")
    op.drop_table("company_qualification_profile_completeness")
