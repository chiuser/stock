"""add class member person type

Revision ID: 20260705_0006
Revises: 20260705_0005
Create Date: 2026-07-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260705_0006"
down_revision = "20260705_0005"
branch_labels = None
depends_on = None


NEW_PERSON_TYPES = "'member', 'coach', 'staff', 'class_member', 'stranger', 'unknown_known'"
OLD_PERSON_TYPES = "'member', 'coach', 'staff', 'stranger', 'unknown_known'"


def upgrade() -> None:
    op.create_table(
        "class_members",
        sa.Column("class_member_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("face_group_id", sa.Text()),
        sa.Column("camera_person_id", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.drop_constraint("ck_attendance_events_person_type", "attendance_events", type_="check")
    op.create_check_constraint(
        "ck_attendance_events_person_type",
        "attendance_events",
        f"person_type in ({NEW_PERSON_TYPES})",
    )
    op.add_column(
        "daily_attendance_reports",
        sa.Column(
            "class_member_entries",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.execute(
        """
        delete from feishu_notifications
        where attendance_event_id in (
          select event_id from attendance_events where person_type = 'class_member'
        );
        """
    )
    op.execute("delete from attendance_events where person_type = 'class_member';")
    op.drop_constraint("ck_attendance_events_person_type", "attendance_events", type_="check")
    op.create_check_constraint(
        "ck_attendance_events_person_type",
        "attendance_events",
        f"person_type in ({OLD_PERSON_TYPES})",
    )
    op.drop_column("daily_attendance_reports", "class_member_entries")
    op.drop_table("class_members")
