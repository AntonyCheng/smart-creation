"""Add vision-capability tracking and a standalone image-generation backend catalog."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260912_0023"
down_revision = "20260902_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("provider_models", sa.Column("supports_vision", sa.Boolean(), nullable=True))
    op.create_table(
        "image_providers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("backend", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("api_key_ciphertext", sa.Text(), nullable=False),
        sa.Column("api_key_hint", sa.String(24), nullable=False),
        sa.Column("base_url_override", sa.String(1024), nullable=True),
        sa.Column("model_override", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_test_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("image_providers")
    op.drop_column("provider_models", "supports_vision")
