"""Permit core-requirement verdicts while retaining historical status rows.

Revision ID: 026_core_requirement_status
Revises: 025_analysis_input_fingerprint
"""

from alembic import op


revision = "026_core_requirement_status"
down_revision = "025_analysis_input_fingerprint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "qualification_judgment_runs_overall_status_valid",
        "qualification_judgment_runs",
        type_="check",
    )
    op.create_check_constraint(
        "qualification_judgment_runs_overall_status_valid",
        "qualification_judgment_runs",
        "overall_status IN ('eligible', 'ineligible', 'insufficient_data', 'core_met', 'core_unmet', 'needs_review')",
    )


def downgrade() -> None:
    # Do not rewrite or silently discard verdict history on rollback.
    op.execute("""DO $$ BEGIN
        IF EXISTS (
            SELECT 1 FROM qualification_judgment_runs
            WHERE overall_status IN ('core_met', 'core_unmet', 'needs_review')
        ) THEN
            RAISE EXCEPTION 'Cannot downgrade core-requirement statuses while new verdicts exist';
        END IF;
    END $$""")
    op.drop_constraint(
        "qualification_judgment_runs_overall_status_valid",
        "qualification_judgment_runs",
        type_="check",
    )
    op.create_check_constraint(
        "qualification_judgment_runs_overall_status_valid",
        "qualification_judgment_runs",
        "overall_status IN ('eligible', 'ineligible', 'insufficient_data')",
    )
