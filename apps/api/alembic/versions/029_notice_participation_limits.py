"""Keep 나라장터's structured participation limits with each notice version.

The notice list API only says *that* an industry restriction exists. The values
live in two separate lookups — 면허제한(getBidPblancListInfoLicenseLimit) and
참가가능지역(getBidPblancListInfoPrtcptPsblRgn). From 2026-10-10 the qualification
analysis reads them as a second source next to the notice documents: a licence or
region the documents did not yield still becomes a requirement.

The value is fetched once, when a version is first analysed, and stored here so a
re-analysis sees the same input. NULL means "not fetched yet", which is different
from a fetched value with empty lists ("the agency entered no limits").
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "029_notice_participation_limits"
down_revision = "028_notice_processing_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bid_notice_versions", sa.Column("participation_limits", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("bid_notice_versions", "participation_limits")
