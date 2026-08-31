"""Add structured creation presets to reusable prompts."""

from alembic import op
import sqlalchemy as sa


revision = "20260823_0015"
down_revision = "20260822_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "prompt_snippets",
        sa.Column("preset", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
    )
    op.alter_column("prompt_snippets", "preset", server_default=None)


def downgrade() -> None:
    op.drop_column("prompt_snippets", "preset")
