"""store camera person ids as text

Revision ID: 20260703_0002
Revises: 20260703_0001
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260703_0002"
down_revision = "20260703_0001"
branch_labels = None
depends_on = None


KNOWN_PERSON_TABLES = ("members", "coaches", "staff")


def upgrade() -> None:
    for table_name in KNOWN_PERSON_TABLES:
        op.alter_column(
            table_name,
            "camera_person_id",
            existing_type=sa.Integer(),
            type_=sa.Text(),
            existing_nullable=True,
            postgresql_using="camera_person_id::text",
        )


def downgrade() -> None:
    for table_name in KNOWN_PERSON_TABLES:
        op.alter_column(
            table_name,
            "camera_person_id",
            existing_type=sa.Text(),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using=(
                "case "
                "when camera_person_id ~ '^-?[0-9]+$' "
                "and camera_person_id::numeric between -2147483648 and 2147483647 "
                "then camera_person_id::integer "
                "else null "
                "end"
            ),
        )
