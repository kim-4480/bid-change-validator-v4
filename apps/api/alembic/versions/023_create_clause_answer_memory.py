"""Store the first model answer per clause so re-analysis gives the same Requirements.

The extraction model (gpt-6-luna) rejects temperature and does not honour seed:
the same clause sent four times came back with four different labels (2026-10-06).
Analysing a notice again, or the next notice version with unchanged clauses, then
produced different Requirements and false "changed" diffs. The engine already
accepts memories for clause labels, polarity and clause selection; this table makes
them survive across requests and restarts.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "023_clause_answer_memory"
down_revision = "022_notice_history_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clause_answer_memory",
        # label | polarity | selection — which engine memory the answer belongs to.
        sa.Column("kind", sa.Text(), nullable=False),
        # Engine-made key: hash of the clause text (and section path / prompt version).
        sa.Column("clause_key", sa.Text(), nullable=False),
        sa.Column("answer", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("kind", "clause_key", name="pk_clause_answer_memory"),
    )


def downgrade() -> None:
    op.drop_table("clause_answer_memory")
