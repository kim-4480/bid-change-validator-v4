"""Keep the engine's coverage (checklist gaps, notes) with each analysis run.

From 2026-10-07 the overall verdict only uses closed values (industry code, region,
company size, product number). Everything else becomes a checklist item the user
confirms, and joint-venture/subcontracting lines become notes. The verdict needs to
know whether any closed value was left unread (coverage.verdict_complete), and the
screen needs the checklist and notes, so the coverage is stored next to the run.
Runs made before this migration have NULL and keep the old analysis-status rule.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "024_analysis_run_coverage"
down_revision = "023_clause_answer_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("qualification_analysis_runs", sa.Column("coverage", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("qualification_analysis_runs", "coverage")
