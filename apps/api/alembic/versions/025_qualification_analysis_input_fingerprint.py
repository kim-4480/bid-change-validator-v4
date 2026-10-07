"""Add qualification analysis input fingerprint.

Revision ID: 025_analysis_input_fingerprint
Revises: 024_analysis_run_coverage
"""

from alembic import op
import sqlalchemy as sa


revision = "025_analysis_input_fingerprint"
down_revision = "024_analysis_run_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qualification_analysis_runs",
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("qualification_analysis_runs", "input_fingerprint")
