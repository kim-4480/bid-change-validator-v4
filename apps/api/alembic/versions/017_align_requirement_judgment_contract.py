"""Align persisted requirements and judgments with the product contract."""

from alembic import op
import sqlalchemy as sa


revision = "017_req_judgment_contract"
down_revision = "016_notice_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qualification_requirements",
        sa.Column("requirement_role", sa.Text(), nullable=False, server_default="mandatory"),
    )
    op.add_column(
        "qualification_requirements",
        sa.Column("condition_complexity", sa.Text(), nullable=False, server_default="simple"),
    )
    op.execute(
        """
        UPDATE qualification_requirements
        SET requirement_role = CASE WHEN required THEN 'mandatory' ELSE 'preferred' END
        """
    )
    op.create_check_constraint(
        "qualification_requirements_role_valid",
        "qualification_requirements",
        "requirement_role IN ('mandatory', 'preferred', 'informational')",
    )
    op.create_check_constraint(
        "qualification_requirements_complexity_valid",
        "qualification_requirements",
        "condition_complexity IN ('simple', 'composite')",
    )

    op.add_column(
        "qualification_judgments",
        sa.Column("value_source", sa.Text(), nullable=False, server_default="none"),
    )
    op.add_column(
        "qualification_judgments",
        sa.Column("evidence_status", sa.Text(), nullable=False, server_default="none"),
    )
    op.add_column("qualification_judgments", sa.Column("unknown_reason", sa.Text()))
    op.execute(
        """
        UPDATE qualification_judgments
        SET value_source = CASE basis_type
                WHEN 'PROFILE' THEN 'stored_profile'
                WHEN 'USER_ANSWER' THEN 'askback'
                ELSE 'none'
            END,
            evidence_status = CASE WHEN evidence_held THEN 'declared' ELSE 'none' END,
            unknown_reason = CASE
                WHEN status <> 'UNKNOWN' THEN NULL
                WHEN reason_code IN ('NEEDS_REVIEW', 'UNSUPPORTED_REQUIREMENT')
                    THEN 'requirement_uncertain'
                ELSE 'profile_missing'
            END
        """
    )
    op.create_check_constraint(
        "qualification_judgments_value_source_valid",
        "qualification_judgments",
        "value_source IN ('stored_profile', 'askback', 'none')",
    )
    op.create_check_constraint(
        "qualification_judgments_evidence_status_valid",
        "qualification_judgments",
        "evidence_status IN ('none', 'declared', 'uploaded')",
    )
    op.create_check_constraint(
        "qualification_judgments_unknown_reason_valid",
        "qualification_judgments",
        "unknown_reason IS NULL OR unknown_reason IN "
        "('profile_missing', 'requirement_uncertain', 'evidence_missing')",
    )
    op.create_check_constraint(
        "qualification_judgments_unknown_reason_consistent",
        "qualification_judgments",
        "(status = 'UNKNOWN' AND unknown_reason IS NOT NULL) OR "
        "(status <> 'UNKNOWN' AND unknown_reason IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "qualification_judgments_unknown_reason_consistent",
        "qualification_judgments",
        type_="check",
    )
    op.drop_constraint(
        "qualification_judgments_unknown_reason_valid",
        "qualification_judgments",
        type_="check",
    )
    op.drop_constraint(
        "qualification_judgments_evidence_status_valid",
        "qualification_judgments",
        type_="check",
    )
    op.drop_constraint(
        "qualification_judgments_value_source_valid",
        "qualification_judgments",
        type_="check",
    )
    op.drop_column("qualification_judgments", "unknown_reason")
    op.drop_column("qualification_judgments", "evidence_status")
    op.drop_column("qualification_judgments", "value_source")

    op.drop_constraint(
        "qualification_requirements_complexity_valid",
        "qualification_requirements",
        type_="check",
    )
    op.drop_constraint(
        "qualification_requirements_role_valid",
        "qualification_requirements",
        type_="check",
    )
    op.drop_column("qualification_requirements", "condition_complexity")
    op.drop_column("qualification_requirements", "requirement_role")
