"""Persist changed-notice qualification revalidation lineage."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "009_qualification_revalidation"
down_revision = "008_qualification_answers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qualification_revalidation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("preflight_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("preflight_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_judgment_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_judgment_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("baseline_analysis_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("current_analysis_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("revalidated_keys", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "idx_qualification_revalidation_runs_case_created",
        "qualification_revalidation_runs",
        ["preflight_case_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_qualification_revalidation_runs_case_created",
        table_name="qualification_revalidation_runs",
    )
    op.drop_table("qualification_revalidation_runs")
