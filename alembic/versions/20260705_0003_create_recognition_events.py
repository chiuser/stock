"""create recognition monitor events table

Revision ID: 20260705_0003
Revises: 20260703_0002
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260705_0003"
down_revision = "20260703_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recognition_events",
        sa.Column("recognition_event_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_dedupe_key", sa.Text(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("camera_serial_number", sa.Text()),
        sa.Column("camera_event_id", sa.Text()),
        sa.Column("operator", sa.Text(), nullable=False, server_default=sa.text("'FaceReco'")),
        sa.Column("camera_result", sa.Text(), nullable=False),
        sa.Column("camera_person_name", sa.Text()),
        sa.Column("camera_person_id", sa.Text()),
        sa.Column("camera_person_role", sa.Text()),
        sa.Column("camera_person_role_name", sa.Text()),
        sa.Column("recheck_status", sa.Text(), nullable=False, server_default=sa.text("'not_rechecked'")),
        sa.Column("recheck_reason", sa.Text()),
        sa.Column("face_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("quality_flags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("det_score", sa.Double()),
        sa.Column("face_width", sa.Double()),
        sa.Column("face_height", sa.Double()),
        sa.Column("blur_score", sa.Double()),
        sa.Column("frontal_score", sa.Double()),
        sa.Column("gallery_accepted", sa.Boolean()),
        sa.Column("gallery_name", sa.Text()),
        sa.Column("gallery_person_id", sa.Text()),
        sa.Column("gallery_person_type", sa.Text()),
        sa.Column("gallery_group_name", sa.Text()),
        sa.Column("gallery_similarity", sa.Double()),
        sa.Column("gallery_second_similarity", sa.Double()),
        sa.Column("gallery_camera_identity_status", sa.Text()),
        sa.Column("gallery_top5_candidates", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("classification", sa.Text(), nullable=False),
        sa.Column("background_relative_path", sa.Text()),
        sa.Column("background_content_type", sa.Text()),
        sa.Column("capture_relative_path", sa.Text()),
        sa.Column("capture_content_type", sa.Text()),
        sa.Column("insightface_crop_relative_path", sa.Text()),
        sa.Column("insightface_crop_content_type", sa.Text()),
        sa.Column("record_relative_path", sa.Text()),
        sa.Column("raw_relative_path", sa.Text()),
        sa.Column("face_recheck", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("event_dedupe_key", name="uq_recognition_events_event_dedupe_key"),
    )
    op.create_index("idx_recognition_events_date_time", "recognition_events", ["event_date", sa.text("event_time DESC")])
    op.create_index("idx_recognition_events_date_classification", "recognition_events", ["event_date", "classification"])
    op.create_index("idx_recognition_events_date_camera_result", "recognition_events", ["event_date", "camera_result"])
    op.create_index("idx_recognition_events_date_recheck_status", "recognition_events", ["event_date", "recheck_status"])
    op.create_index("idx_recognition_events_camera_person_id", "recognition_events", ["camera_person_id"])
    op.create_index("idx_recognition_events_gallery_person_id", "recognition_events", ["gallery_person_id"])


def downgrade() -> None:
    op.drop_index("idx_recognition_events_gallery_person_id", table_name="recognition_events")
    op.drop_index("idx_recognition_events_camera_person_id", table_name="recognition_events")
    op.drop_index("idx_recognition_events_date_recheck_status", table_name="recognition_events")
    op.drop_index("idx_recognition_events_date_camera_result", table_name="recognition_events")
    op.drop_index("idx_recognition_events_date_classification", table_name="recognition_events")
    op.drop_index("idx_recognition_events_date_time", table_name="recognition_events")
    op.drop_table("recognition_events")
