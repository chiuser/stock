"""create attendance tables

Revision ID: 20260703_0001
Revises:
Create Date: 2026-07-03
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260703_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("member_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("face_group_id", sa.Text()),
        sa.Column("camera_person_id", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "coaches",
        sa.Column("coach_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("face_group_id", sa.Text()),
        sa.Column("camera_person_id", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "staff",
        sa.Column("staff_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("face_group_id", sa.Text()),
        sa.Column("camera_person_id", sa.Integer()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "strangers",
        sa.Column("stranger_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("image_path", sa.Text()),
        sa.Column("image_url", sa.Text()),
        sa.Column("image_token_hash", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_table(
        "attendance_events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_dedupe_key", sa.Text(), nullable=False),
        sa.Column("camera_serial_number", sa.Text()),
        sa.Column("camera_event_id", sa.Text()),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("person_type", sa.Text(), nullable=False),
        sa.Column("person_ref_id", sa.Text()),
        sa.Column("person_name", sa.Text()),
        sa.Column("face_group_id", sa.Text()),
        sa.Column("face_group_name", sa.Text()),
        sa.Column("match_number", sa.Integer()),
        sa.Column("image_source", sa.Text()),
        sa.Column("image_path", sa.Text()),
        sa.Column("image_url", sa.Text()),
        sa.Column("raw_event_path", sa.Text()),
        sa.Column("delivery_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("should_notify", sa.Boolean(), nullable=False),
        sa.Column("notification_suppressed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("suppressed_reason", sa.Text()),
        sa.Column("dedupe_reference_event_id", sa.BigInteger()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "person_type in ('member', 'coach', 'staff', 'stranger', 'unknown_known')",
            name="ck_attendance_events_person_type",
        ),
        sa.ForeignKeyConstraint(
            ["dedupe_reference_event_id"],
            ["attendance_events.event_id"],
            name="fk_attendance_events_dedupe_reference_event_id",
        ),
        sa.UniqueConstraint("event_dedupe_key", name="uq_attendance_events_event_dedupe_key"),
    )
    op.create_table(
        "feishu_notifications",
        sa.Column("notification_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("attendance_event_id", sa.BigInteger(), nullable=False),
        sa.Column("should_send", sa.Boolean(), nullable=False),
        sa.Column("send_status", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("suppressed_reason", sa.Text()),
        sa.Column("response_status_code", sa.Integer()),
        sa.Column("response_text", sa.Text()),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "send_status in ('pending', 'sent', 'suppressed', 'failed')",
            name="ck_feishu_notifications_send_status",
        ),
        sa.ForeignKeyConstraint(
            ["attendance_event_id"],
            ["attendance_events.event_id"],
            name="fk_feishu_notifications_attendance_event_id",
        ),
    )
    op.create_table(
        "daily_attendance_reports",
        sa.Column("report_date", sa.Date(), primary_key=True),
        sa.Column("member_entries", sa.Integer(), nullable=False),
        sa.Column("coach_entries", sa.Integer(), nullable=False),
        sa.Column("staff_entries", sa.Integer(), nullable=False),
        sa.Column("stranger_entries", sa.Integer(), nullable=False),
        sa.Column("unknown_known_entries", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("notification_sent_count", sa.Integer(), nullable=False),
        sa.Column("notification_suppressed_count", sa.Integer(), nullable=False),
        sa.Column("stranger_items", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("idx_attendance_events_time", "attendance_events", ["event_time"])
    op.create_index(
        "idx_attendance_events_person_window",
        "attendance_events",
        ["person_type", "person_ref_id", sa.text("event_time DESC")],
        postgresql_where=sa.text(
            "person_type <> 'stranger' and should_notify = true and notification_suppressed = false"
        ),
    )
    op.create_index("idx_attendance_events_report", "attendance_events", ["event_time", "person_type"])
    op.create_index(
        "idx_attendance_events_camera",
        "attendance_events",
        ["camera_serial_number", "camera_event_id"],
    )
    op.create_index("idx_feishu_notifications_event", "feishu_notifications", ["attendance_event_id"])
    op.create_index("idx_strangers_first_seen", "strangers", ["first_seen_at"])


def downgrade() -> None:
    op.drop_index("idx_strangers_first_seen", table_name="strangers")
    op.drop_index("idx_feishu_notifications_event", table_name="feishu_notifications")
    op.drop_index("idx_attendance_events_camera", table_name="attendance_events")
    op.drop_index("idx_attendance_events_report", table_name="attendance_events")
    op.drop_index("idx_attendance_events_person_window", table_name="attendance_events")
    op.drop_index("idx_attendance_events_time", table_name="attendance_events")
    op.drop_table("daily_attendance_reports")
    op.drop_table("feishu_notifications")
    op.drop_table("attendance_events")
    op.drop_table("strangers")
    op.drop_table("staff")
    op.drop_table("coaches")
    op.drop_table("members")
