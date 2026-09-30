"""Persist canonical qualification analysis runs, requirements, and evidence."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "006_qualification_analysis"
down_revision = "005_preflight_cases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qualification_analysis_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "notice_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notice_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contract_version", sa.Text(), nullable=False),
        sa.Column("analysis_kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "target_chunk_ids",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "diagnostics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('SUCCEEDED', 'PARTIAL', 'FAILED')",
            name="qualification_analysis_runs_status_valid",
        ),
    )
    op.create_index(
        "idx_qualification_analysis_runs_version_created",
        "qualification_analysis_runs",
        ["notice_version_id", "created_at"],
    )

    op.create_table(
        "qualification_requirements",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "analysis_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("requirement_key", sa.Text(), nullable=False),
        sa.Column("requirement_group_key", sa.Text()),
        sa.Column("group_operator", sa.Text()),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("operator", sa.Text()),
        sa.Column("value_json", postgresql.JSONB()),
        sa.Column("unit", sa.Text()),
        sa.Column("period_months", sa.Numeric(12, 3)),
        sa.Column(
            "scope",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("raw", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(6, 5)),
        sa.Column(
            "evidence_keys",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "analysis_run_id",
            "requirement_key",
            name="uq_qualification_requirement_run_key",
        ),
    )
    op.create_index(
        "idx_qualification_requirements_run_type",
        "qualification_requirements",
        ["analysis_run_id", "type"],
    )

    op.create_table(
        "qualification_evidence",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "analysis_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("qualification_analysis_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_key", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("notice_version_id", sa.Text()),
        sa.Column("case_id", sa.Text()),
        sa.Column("chunk_id", sa.Text()),
        sa.Column(
            "location",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.Text()),
        sa.Column("extracted_text_sha256", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "analysis_run_id",
            "evidence_key",
            name="uq_qualification_evidence_run_key",
        ),
    )
    op.create_index(
        "idx_qualification_evidence_run",
        "qualification_evidence",
        ["analysis_run_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_qualification_evidence_run", table_name="qualification_evidence")
    op.drop_table("qualification_evidence")
    op.drop_index(
        "idx_qualification_requirements_run_type",
        table_name="qualification_requirements",
    )
    op.drop_table("qualification_requirements")
    op.drop_index(
        "idx_qualification_analysis_runs_version_created",
        table_name="qualification_analysis_runs",
    )
    op.drop_table("qualification_analysis_runs")
