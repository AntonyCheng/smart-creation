"""Add the creation-mode snapshot columns to projects and jobs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260901_0021"
down_revision = "20260831_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("mode", sa.String(32), nullable=True))
    op.add_column("jobs", sa.Column("mode", sa.String(32), nullable=True))
    # Existing gongwen projects were all created through the drafting flow.
    op.execute("UPDATE projects SET mode = 'draft' WHERE skill_id = 'gongwen' AND mode IS NULL")
    op.execute("UPDATE jobs SET mode = 'draft' WHERE skill_id = 'gongwen' AND mode IS NULL")


def downgrade() -> None:
    op.drop_column("jobs", "mode")
    op.drop_column("projects", "mode")
