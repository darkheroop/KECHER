"""bot setting value text

Revision ID: e9c8b568f682
Revises: 0bd957a4feb0
Create Date: 2026-09-16 22:28:14.041958

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9c8b568f682'
down_revision: Union[str, None] = '0bd957a4feb0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Batch mode so this also works on SQLite (recreates the table).
    with op.batch_alter_table("bot_settings") as batch:
        batch.alter_column(
            "value", existing_type=sa.VARCHAR(length=256), type_=sa.Text(), existing_nullable=False
        )


def downgrade() -> None:
    with op.batch_alter_table("bot_settings") as batch:
        batch.alter_column(
            "value", existing_type=sa.Text(), type_=sa.VARCHAR(length=256), existing_nullable=False
        )
