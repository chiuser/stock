"""add final recognition decision fields

Revision ID: 20260705_0005
Revises: 20260705_0004
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_0005"
down_revision = "20260705_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recognition_events",
        sa.Column(
            "final_recognition_decision",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("recognition_event_faces", sa.Column("business_action", sa.Text()))
    op.add_column("recognition_event_faces", sa.Column("suppress_reason", sa.Text()))
    op.create_index(
        "idx_recognition_event_faces_business_action",
        "recognition_event_faces",
        ["business_action"],
    )


def downgrade() -> None:
    op.drop_index("idx_recognition_event_faces_business_action", table_name="recognition_event_faces")
    op.drop_column("recognition_event_faces", "suppress_reason")
    op.drop_column("recognition_event_faces", "business_action")
    op.drop_column("recognition_events", "final_recognition_decision")
