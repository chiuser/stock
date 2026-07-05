"""add recognition face source role

Revision ID: 20260705_0007
Revises: 20260705_0006
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260705_0007"
down_revision = "20260705_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recognition_event_faces",
        sa.Column("source_role", sa.Text(), nullable=False, server_default=sa.text("'scene_face'")),
    )
    op.execute(
        """
        update recognition_event_faces
        set source_role = case
          when image_source = 'capture' then 'camera_target_crop'
          else 'scene_face'
        end;
        """
    )
    op.create_index(
        "idx_recognition_event_faces_source_role",
        "recognition_event_faces",
        ["source_role"],
    )


def downgrade() -> None:
    op.drop_index("idx_recognition_event_faces_source_role", table_name="recognition_event_faces")
    op.drop_column("recognition_event_faces", "source_role")
