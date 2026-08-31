"""Add the multi-skill columns and the docx artifact kind."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260831_0019"
down_revision = "20260825_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLAlchemy persists str-Enums by member NAME (SVG / PPTX / REPORT), so
    # the new kind must be registered under its uppercase name. PostgreSQL
    # also forbids using a newly added enum value in the same transaction,
    # hence this migration only registers the label.
    op.get_bind().execute(sa.text("ALTER TYPE artifact_kind ADD VALUE IF NOT EXISTS 'DOCX'"))
    op.add_column(
        "projects",
        sa.Column("skill_id", sa.String(64), nullable=False, server_default="ppt-master"),
    )
    op.create_index("ix_projects_skill_id", "projects", ["skill_id"])
    op.add_column(
        "jobs",
        sa.Column("skill_id", sa.String(64), nullable=False, server_default="ppt-master"),
    )
    op.create_index("ix_jobs_skill_id", "jobs", ["skill_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_skill_id", table_name="jobs")
    op.drop_column("jobs", "skill_id")
    op.drop_index("ix_projects_skill_id", table_name="projects")
    op.drop_column("projects", "skill_id")
    # PostgreSQL cannot remove an enum value without recreating the type;
    # the dormant 'docx' value is intentionally left in place.