"""Require administrator verification before a model can be used."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260824_0016"
down_revision = "20260823_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_models",
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("provider_models", sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("provider_models", sa.Column("last_test_error", sa.Text(), nullable=True))
    op.alter_column("provider_models", "is_verified", server_default=None)

    # Preserve an existing administrator-selected default, but make the new
    # setting the sole source of truth going forward.
    op.execute(
        """
        INSERT INTO system_settings (key, value)
        SELECT 'default_model_id', p.slug || '/' || m.model_id
        FROM providers p
        JOIN provider_models m ON m.provider_id = p.id
        WHERE m.is_default = true
        ORDER BY m.created_at
        LIMIT 1
        ON CONFLICT (key) DO NOTHING
        """
    )
    op.execute("UPDATE provider_models SET is_default = false")


def downgrade() -> None:
    op.drop_column("provider_models", "last_test_error")
    op.drop_column("provider_models", "last_tested_at")
    op.drop_column("provider_models", "is_verified")
