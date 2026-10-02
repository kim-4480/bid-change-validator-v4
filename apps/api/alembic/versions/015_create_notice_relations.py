"""Persist direct reannouncement links between bid notices."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "015_notice_relations"
down_revision = "014_clause_finding_arrays"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notice_relations",
        sa.Column(
            "notice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notices.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "previous_notice_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("bid_notices.id", ondelete="SET NULL"),
        ),
        sa.Column("previous_bid_notice_no", sa.Text(), nullable=False),
        sa.Column("match_method", sa.Text(), nullable=False),
        sa.Column("match_confidence", sa.Text(), nullable=False),
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
        sa.CheckConstraint(
            "previous_notice_id IS NULL OR previous_notice_id <> notice_id",
            name="notice_relations_not_self_referential",
        ),
        sa.CheckConstraint(
            "match_method IN ('API_FIELD', 'NAME_AGENCY_PRICE', 'MANUAL')",
            name="notice_relations_match_method_valid",
        ),
        sa.CheckConstraint(
            "match_confidence IN ('CONFIRMED', 'SUGGESTED')",
            name="notice_relations_match_confidence_valid",
        ),
    )
    op.create_index(
        "idx_notice_relations_previous_notice",
        "notice_relations",
        ["previous_notice_id"],
    )
    op.create_index(
        "idx_notice_relations_previous_number",
        "notice_relations",
        ["previous_bid_notice_no"],
    )

    # Older snapshots already contain the upstream field in raw_json. Preserve
    # the latest direct predecessor reference even if that notice is not in DB yet.
    op.execute(
        """
        INSERT INTO notice_relations (
            notice_id,
            previous_notice_id,
            previous_bid_notice_no,
            match_method,
            match_confidence
        )
        SELECT
            latest.notice_id,
            CASE WHEN previous.id = latest.notice_id THEN NULL ELSE previous.id END,
            latest.previous_bid_notice_no,
            'API_FIELD',
            'CONFIRMED'
        FROM (
            SELECT DISTINCT ON (notice_id)
                notice_id,
                BTRIM(raw_json ->> 'befBidBbancNo') AS previous_bid_notice_no
            FROM bid_notice_versions
            WHERE NULLIF(BTRIM(raw_json ->> 'befBidBbancNo'), '') IS NOT NULL
            ORDER BY notice_id, version_number DESC
        ) AS latest
        LEFT JOIN bid_notices AS previous
            ON previous.bid_notice_no = latest.previous_bid_notice_no
        """
    )


def downgrade() -> None:
    op.drop_index("idx_notice_relations_previous_number", table_name="notice_relations")
    op.drop_index("idx_notice_relations_previous_notice", table_name="notice_relations")
    op.drop_table("notice_relations")
