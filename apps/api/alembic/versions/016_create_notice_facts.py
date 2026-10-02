"""Create normalized, version-scoped notice facts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "016_notice_facts"
down_revision = "015_notice_relations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notice_facts",
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
        sa.Column("fact_key", sa.Text(), nullable=False),
        sa.Column("value_json", postgresql.JSONB(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_field", sa.Text()),
        sa.Column("raw_value", sa.Text()),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notice_documents.id", ondelete="SET NULL"),
        ),
        sa.Column("evidence_location", postgresql.JSONB()),
        sa.Column("quote", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "notice_version_id", "fact_key", name="uq_notice_fact_version_key"
        ),
        sa.CheckConstraint(
            "fact_key IN ('SUBMISSION_DEADLINE', 'BUDGET_AMOUNT', "
            "'ORDERING_AGENCY', 'JOINT_SUPPLY')",
            name="notice_facts_key_valid",
        ),
        sa.CheckConstraint(
            "source_type IN ('G2B_API', 'DOCUMENT_EXTRACTION', 'MANUAL')",
            name="notice_facts_source_type_valid",
        ),
    )
    op.create_index("idx_notice_facts_version", "notice_facts", ["notice_version_id"])
    op.create_index("idx_notice_facts_key", "notice_facts", ["fact_key"])

    op.execute(
        """
        INSERT INTO notice_facts (
            notice_version_id, fact_key, value_json, source_type, source_field, raw_value
        )
        SELECT id, 'SUBMISSION_DEADLINE',
               jsonb_build_object('at', BTRIM(raw_json ->> 'bidClseDt')),
               'G2B_API', 'bidClseDt', BTRIM(raw_json ->> 'bidClseDt')
        FROM bid_notice_versions
        WHERE NULLIF(BTRIM(raw_json ->> 'bidClseDt'), '') IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO notice_facts (
            notice_version_id, fact_key, value_json, source_type, source_field, raw_value
        )
        SELECT id, 'BUDGET_AMOUNT',
               jsonb_build_object(
                   'amount', REPLACE(BTRIM(COALESCE(
                       NULLIF(raw_json ->> 'asignBdgtAmt', ''),
                       NULLIF(raw_json ->> 'bdgtAmt', '')
                   )), ',', '')::numeric,
                   'currency', 'KRW'
               ),
               'G2B_API',
               CASE WHEN NULLIF(BTRIM(raw_json ->> 'asignBdgtAmt'), '') IS NOT NULL
                    THEN 'asignBdgtAmt' ELSE 'bdgtAmt' END,
               BTRIM(COALESCE(
                   NULLIF(raw_json ->> 'asignBdgtAmt', ''),
                   NULLIF(raw_json ->> 'bdgtAmt', '')
               ))
        FROM bid_notice_versions
        WHERE REPLACE(BTRIM(COALESCE(
            NULLIF(raw_json ->> 'asignBdgtAmt', ''),
            NULLIF(raw_json ->> 'bdgtAmt', '')
        )), ',', '') ~ '^[0-9]+$'
        """
    )
    op.execute(
        """
        INSERT INTO notice_facts (
            notice_version_id, fact_key, value_json, source_type, source_field, raw_value
        )
        SELECT id, 'ORDERING_AGENCY',
               jsonb_build_object(
                   'code', COALESCE(
                       NULLIF(BTRIM(raw_json ->> 'dminsttCd'), ''),
                       NULLIF(BTRIM(raw_json ->> 'ntceInsttCd'), '')
                   ),
                   'name', COALESCE(
                       NULLIF(BTRIM(raw_json ->> 'dminsttNm'), ''),
                       NULLIF(BTRIM(raw_json ->> 'ntceInsttNm'), '')
                   )
               ),
               'G2B_API', 'dminsttCd,dminsttNm',
               COALESCE(
                   NULLIF(BTRIM(raw_json ->> 'dminsttNm'), ''),
                   NULLIF(BTRIM(raw_json ->> 'ntceInsttNm'), ''),
                   NULLIF(BTRIM(raw_json ->> 'dminsttCd'), ''),
                   NULLIF(BTRIM(raw_json ->> 'ntceInsttCd'), '')
               )
        FROM bid_notice_versions
        WHERE COALESCE(
            NULLIF(BTRIM(raw_json ->> 'dminsttNm'), ''),
            NULLIF(BTRIM(raw_json ->> 'ntceInsttNm'), ''),
            NULLIF(BTRIM(raw_json ->> 'dminsttCd'), ''),
            NULLIF(BTRIM(raw_json ->> 'ntceInsttCd'), '')
        ) IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO notice_facts (
            notice_version_id, fact_key, value_json, source_type, source_field, raw_value
        )
        SELECT id, 'JOINT_SUPPLY',
               jsonb_build_object(
                   'status', CASE
                       WHEN raw_json ->> 'cmmnSpldmdMethdNm' LIKE '%불허%'
                       THEN 'not_allowed' ELSE 'allowed' END,
                   'method_code', NULLIF(BTRIM(raw_json ->> 'cmmnSpldmdMethdCd'), ''),
                   'method_name', BTRIM(raw_json ->> 'cmmnSpldmdMethdNm')
               ),
               'G2B_API', 'cmmnSpldmdMethdCd,cmmnSpldmdMethdNm',
               BTRIM(raw_json ->> 'cmmnSpldmdMethdNm')
        FROM bid_notice_versions
        WHERE NULLIF(BTRIM(raw_json ->> 'cmmnSpldmdMethdNm'), '') IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index("idx_notice_facts_key", table_name="notice_facts")
    op.drop_index("idx_notice_facts_version", table_name="notice_facts")
    op.drop_table("notice_facts")
