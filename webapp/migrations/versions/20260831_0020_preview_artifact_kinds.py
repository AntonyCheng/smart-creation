"""Register the pdf and png artifact kinds for rendered previews."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260831_0020"
down_revision = "20260831_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy persists str-Enums by member NAME, so labels are uppercase.
    # Values are only registered here, never used in this transaction.
    op.get_bind().execute(sa.text("ALTER TYPE artifact_kind ADD VALUE IF NOT EXISTS 'PDF'"))
    op.get_bind().execute(sa.text("ALTER TYPE artifact_kind ADD VALUE IF NOT EXISTS 'PNG'"))


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value without recreating the type;
    # the dormant labels are intentionally left in place.
    return None
