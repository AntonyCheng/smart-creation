"""Scope creation presets to one skill."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260902_0022"
down_revision = "20260901_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prompt_snippets", sa.Column("skill_id", sa.String(64), nullable=True))
    op.create_index("ix_prompt_snippets_skill_id", "prompt_snippets", ["skill_id"])
    # Every existing preset was authored against the PPT composer fields.
    op.execute("UPDATE prompt_snippets SET skill_id = 'ppt-master' WHERE skill_id IS NULL")


def downgrade() -> None:
    op.drop_index("ix_prompt_snippets_skill_id", table_name="prompt_snippets")
    op.drop_column("prompt_snippets", "skill_id")
