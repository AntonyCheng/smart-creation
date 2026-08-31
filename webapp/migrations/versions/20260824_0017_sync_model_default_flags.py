"""Keep legacy provider model flags aligned with the explicit default setting."""

from __future__ import annotations

from alembic import op


revision = "20260824_0017"
down_revision = "20260824_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE provider_models m
        SET is_default = EXISTS (
            SELECT 1
            FROM providers p
            JOIN system_settings s ON s.key = 'default_model_id'
            WHERE p.id = m.provider_id
              AND s.value = p.slug || '/' || m.model_id
        )
        """
    )


def downgrade() -> None:
    pass
