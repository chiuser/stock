"""create recognition monitor event face rows

Revision ID: 20260705_0004
Revises: 20260705_0003
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_0004"
down_revision = "20260705_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recognition_events",
        sa.Column(
            "accepted_face_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column("recognition_events", sa.Column("camera_target_face_status", sa.Text()))
    op.add_column(
        "recognition_events",
        sa.Column(
            "has_identity_conflict",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "recognition_event_faces",
        sa.Column("recognition_face_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "recognition_event_id",
            sa.BigInteger(),
            sa.ForeignKey("recognition_events.recognition_event_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("image_source", sa.Text(), nullable=False),
        sa.Column("face_index", sa.Integer(), nullable=False),
        sa.Column("face_key", sa.Text(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("center_x", sa.Double()),
        sa.Column("center_y", sa.Double()),
        sa.Column("face_width", sa.Double()),
        sa.Column("face_height", sa.Double()),
        sa.Column("det_score", sa.Double()),
        sa.Column("blur_score", sa.Double()),
        sa.Column("frontal_score", sa.Double()),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("recheck_status", sa.Text(), nullable=False),
        sa.Column("recheck_reason", sa.Text()),
        sa.Column("gallery_accepted", sa.Boolean()),
        sa.Column("gallery_name", sa.Text()),
        sa.Column("gallery_person_id", sa.Text()),
        sa.Column("gallery_person_type", sa.Text()),
        sa.Column("gallery_group_name", sa.Text()),
        sa.Column("gallery_similarity", sa.Double()),
        sa.Column("gallery_second_similarity", sa.Double()),
        sa.Column("gallery_camera_identity_status", sa.Text()),
        sa.Column("gallery_top5_candidates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("crop_relative_path", sa.Text()),
        sa.Column("crop_content_type", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "recognition_event_id",
            "image_source",
            "face_index",
            name="uq_recognition_event_faces_event_source_index",
        ),
    )
    op.create_index(
        "idx_recognition_event_faces_event",
        "recognition_event_faces",
        ["recognition_event_id", "image_source", "face_index"],
    )
    op.create_index(
        "idx_recognition_event_faces_gallery_person",
        "recognition_event_faces",
        ["gallery_person_id"],
    )
    op.create_index(
        "idx_recognition_event_faces_gallery_accepted",
        "recognition_event_faces",
        ["gallery_accepted"],
    )
    op.create_index(
        "idx_recognition_event_faces_status",
        "recognition_event_faces",
        ["recheck_status"],
    )


def downgrade() -> None:
    op.drop_index("idx_recognition_event_faces_status", table_name="recognition_event_faces")
    op.drop_index("idx_recognition_event_faces_gallery_accepted", table_name="recognition_event_faces")
    op.drop_index("idx_recognition_event_faces_gallery_person", table_name="recognition_event_faces")
    op.drop_index("idx_recognition_event_faces_event", table_name="recognition_event_faces")
    op.drop_table("recognition_event_faces")
    op.drop_column("recognition_events", "has_identity_conflict")
    op.drop_column("recognition_events", "camera_target_face_status")
    op.drop_column("recognition_events", "accepted_face_count")
