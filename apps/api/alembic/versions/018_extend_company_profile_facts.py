"""Preserve coded certifications, staff career, and year-only performances."""

from alembic import op
import sqlalchemy as sa


revision = "018_company_profile_facts"
down_revision = "017_req_judgment_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "company_certifications",
        sa.Column("certification_code", sa.Text()),
    )
    op.create_check_constraint(
        "company_certifications_code_not_blank",
        "company_certifications",
        "certification_code IS NULL OR BTRIM(certification_code) <> ''",
    )
    op.create_index(
        "idx_company_certifications_company_code",
        "company_certifications",
        ["company_id", "certification_code"],
    )

    op.add_column(
        "company_staff_roles",
        sa.Column("career_years", sa.Numeric(5, 2)),
    )
    op.create_check_constraint(
        "company_staff_roles_career_years_nonnegative",
        "company_staff_roles",
        "career_years IS NULL OR career_years >= 0",
    )

    op.drop_constraint(
        "company_performances_date_order",
        "company_performances",
        type_="check",
    )
    op.alter_column("company_performances", "completed_at", nullable=True)
    op.add_column(
        "company_performances",
        sa.Column("completed_year", sa.SmallInteger()),
    )
    op.create_check_constraint(
        "company_performances_completion_known",
        "company_performances",
        "(completed_at IS NOT NULL) <> (completed_year IS NOT NULL)",
    )
    op.create_check_constraint(
        "company_performances_completed_year_valid",
        "company_performances",
        "completed_year IS NULL OR completed_year BETWEEN 1900 AND 2100",
    )
    op.create_check_constraint(
        "company_performances_date_order",
        "company_performances",
        "started_at IS NULL OR completed_at IS NULL OR started_at <= completed_at",
    )
    op.create_check_constraint(
        "company_performances_year_order",
        "company_performances",
        "started_at IS NULL OR completed_year IS NULL OR EXTRACT(YEAR FROM started_at) <= completed_year",
    )


def downgrade() -> None:
    op.drop_constraint(
        "company_performances_year_order",
        "company_performances",
        type_="check",
    )
    op.drop_constraint(
        "company_performances_date_order",
        "company_performances",
        type_="check",
    )
    op.drop_constraint(
        "company_performances_completed_year_valid",
        "company_performances",
        type_="check",
    )
    op.drop_constraint(
        "company_performances_completion_known",
        "company_performances",
        type_="check",
    )
    op.execute(
        """
        UPDATE company_performances
        SET completed_at = make_date(completed_year, 12, 31)
        WHERE completed_at IS NULL
        """
    )
    op.drop_column("company_performances", "completed_year")
    op.alter_column("company_performances", "completed_at", nullable=False)
    op.create_check_constraint(
        "company_performances_date_order",
        "company_performances",
        "started_at IS NULL OR started_at <= completed_at",
    )

    op.drop_constraint(
        "company_staff_roles_career_years_nonnegative",
        "company_staff_roles",
        type_="check",
    )
    op.drop_column("company_staff_roles", "career_years")

    op.drop_index(
        "idx_company_certifications_company_code",
        table_name="company_certifications",
    )
    op.drop_constraint(
        "company_certifications_code_not_blank",
        "company_certifications",
        type_="check",
    )
    op.drop_column("company_certifications", "certification_code")
