"""Persist ask-back answers for partial re-judgment."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision="008_qualification_answers"
down_revision="007_qualification_judgment"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table(
        "qualification_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("preflight_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("preflight_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_judgment_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_judgment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_judgment_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("qualification_judgment_runs.id", ondelete="SET NULL")),
        sa.Column("requirement_key", sa.Text(), nullable=False),
        sa.Column("answer_json", postgresql.JSONB(), nullable=False),
        sa.Column("normalized_value", sa.Text()),
        sa.Column("evidence_held", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("apply_to_profile", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("source_judgment_run_id","requirement_key",name="uq_qualification_answer_source_requirement"),
    )
    op.create_index("idx_qualification_answers_case_created","qualification_answers",["preflight_case_id","created_at"])
def downgrade():
    op.drop_index("idx_qualification_answers_case_created", table_name="qualification_answers")
    op.drop_table("qualification_answers")
