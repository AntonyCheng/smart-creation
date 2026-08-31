"""Record the one child job allowed to resume a cancelled job."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260825_0018"
down_revision = "20260824_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("resumed_by_job_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_jobs_resumed_by_job_id",
        "jobs",
        "jobs",
        ["resumed_by_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("uq_jobs_resumed_by_job_id", "jobs", ["resumed_by_job_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_jobs_resumed_by_job_id", table_name="jobs")
    op.drop_constraint("fk_jobs_resumed_by_job_id", "jobs", type_="foreignkey")
    op.drop_column("jobs", "resumed_by_job_id")
