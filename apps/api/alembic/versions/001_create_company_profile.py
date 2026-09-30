"""Create company profile and master-code tables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "001_company_profile"
down_revision = None
branch_labels = None
depends_on = None

VERIFICATION_COMMENT = (
    "Whether the company marked supporting evidence as held; not third-party verification."
)


def _master_code_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("changed_at", sa.DateTime(timezone=True)),
        sa.Column("source_window", sa.Text()),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "raw_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(f"idx_{name}_name", name, ["name"])


def upgrade() -> None:
    _master_code_table("industry_codes")
    _master_code_table("product_codes")
    _master_code_table("institution_codes")

    op.create_table(
        "companies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("business_registration_number", sa.String(10), unique=True),
        sa.Column("region_code", sa.Text()),
        sa.Column("region_name", sa.Text()),
        sa.Column("company_size", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("BTRIM(name) <> ''", name="companies_name_not_blank"),
        sa.CheckConstraint(
            "business_registration_number IS NULL OR business_registration_number ~ '^[0-9]{10}$'",
            name="companies_business_number_format",
        ),
        sa.CheckConstraint(
            "company_size IN ('MICRO', 'SMALL', 'MEDIUM', 'MID_SIZED', 'LARGE', 'NONE')",
            name="companies_size_valid",
        ),
    )

    op.create_table(
        "company_industries",
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "industry_code",
            sa.Text(),
            sa.ForeignKey("industry_codes.code"),
            primary_key=True,
        ),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=VERIFICATION_COMMENT,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )

    op.create_table(
        "company_staff",
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=VERIFICATION_COMMENT,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("total_count >= 0", name="company_staff_total_nonnegative"),
    )

    op.create_table(
        "company_staff_roles",
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role_name", sa.Text(), primary_key=True),
        sa.Column("headcount", sa.Integer(), nullable=False),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=VERIFICATION_COMMENT,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("BTRIM(role_name) <> ''", name="company_staff_roles_name_not_blank"),
        sa.CheckConstraint("headcount >= 0", name="company_staff_roles_headcount_nonnegative"),
    )

    op.create_table(
        "company_performances",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("client_name", sa.Text()),
        sa.Column(
            "client_institution_code", sa.Text(), sa.ForeignKey("institution_codes.code")
        ),
        sa.Column("amount", sa.Numeric(18, 0), nullable=False),
        sa.Column("started_at", sa.Date()),
        sa.Column("completed_at", sa.Date(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=VERIFICATION_COMMENT,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("BTRIM(name) <> ''", name="company_performances_name_not_blank"),
        sa.CheckConstraint("amount >= 0", name="company_performances_amount_nonnegative"),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at <= completed_at",
            name="company_performances_date_order",
        ),
    )
    op.create_index(
        "idx_company_performances_company_completed",
        "company_performances",
        ["company_id", sa.text("completed_at DESC")],
    )

    op.create_table(
        "company_performance_fields",
        sa.Column(
            "performance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("company_performances.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("field_name", sa.Text(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(
            "BTRIM(field_name) <> ''", name="company_performance_fields_name_not_blank"
        ),
    )

    op.create_table(
        "company_certifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("certificate_number", sa.Text()),
        sa.Column("issuer_name", sa.Text()),
        sa.Column("issued_at", sa.Date()),
        sa.Column("expires_at", sa.Date()),
        sa.Column(
            "verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=VERIFICATION_COMMENT,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("BTRIM(name) <> ''", name="company_certifications_name_not_blank"),
        sa.CheckConstraint(
            "issued_at IS NULL OR expires_at IS NULL OR issued_at <= expires_at",
            name="company_certifications_date_order",
        ),
    )
    op.create_index(
        "idx_company_certifications_company", "company_certifications", ["company_id"]
    )

    op.execute(
        """
        CREATE FUNCTION set_updated_at()
        RETURNS TRIGGER
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in (
        "companies",
        "company_staff",
        "company_staff_roles",
        "company_performances",
        "company_certifications",
    ):
        op.execute(
            f"""
            CREATE TRIGGER {table_name}_set_updated_at
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
            """
        )


def downgrade() -> None:
    op.drop_table("company_performance_fields")
    op.drop_index("idx_company_certifications_company", table_name="company_certifications")
    op.drop_table("company_certifications")
    op.drop_index(
        "idx_company_performances_company_completed", table_name="company_performances"
    )
    op.drop_table("company_performances")
    op.drop_table("company_staff_roles")
    op.drop_table("company_staff")
    op.drop_table("company_industries")
    op.drop_table("companies")
    op.drop_index("idx_institution_codes_name", table_name="institution_codes")
    op.drop_table("institution_codes")
    op.drop_index("idx_product_codes_name", table_name="product_codes")
    op.drop_table("product_codes")
    op.drop_index("idx_industry_codes_name", table_name="industry_codes")
    op.drop_table("industry_codes")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
