"""Validate attendance DB writes, deduplication, and daily report aggregation."""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.config import AttendanceDbSettings, load_env_file
from app.db.session import transaction
from app.services import attendance, event_store, reports

VALIDATION_DATE = date(2099, 1, 1)
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def main() -> int:
    args = parse_args()
    if args.env_file:
        load_env_file(args.env_file)

    settings = AttendanceDbSettings.from_env()
    prefix = f"p6s-validation-{uuid.uuid4().hex[:12]}"
    result: dict[str, Any] = {"prefix": prefix, "validation_date": VALIDATION_DATE.isoformat()}

    try:
        cleanup(prefix, settings)
        result.update(run_validation(prefix, settings))
        if not args.keep_data:
            cleanup(prefix, settings)
            result["cleanup"] = "deleted"
        else:
            result["cleanup"] = "kept"
    except Exception as exc:
        cleanup(prefix, settings)
        result["ok"] = False
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
        return 1

    result["ok"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.local")
    parser.add_argument("--keep-data", action="store_true", help="Keep validation rows for debugging.")
    return parser.parse_args()


def run_validation(prefix: str, settings: AttendanceDbSettings) -> dict[str, Any]:
    base_time = datetime(2099, 1, 1, 10, 0, tzinfo=LOCAL_TZ)
    member_id = f"{prefix}-member"
    class_member_id = f"{prefix}-class-member"
    dedup_settings = replace(settings, attendance_notify_dedup_enabled=True)

    first = attendance.record_event(
        known_draft(
            prefix=prefix,
            suffix="known-1",
            event_time=base_time,
            person_ref_id=member_id,
            camera_person_id="3427976339944670",
        ),
        settings=dedup_settings,
    )
    assert first.inserted and first.should_notify and not first.notification_suppressed

    attendance.safe_record_notification(
        first,
        feishu_result={"ok": True, "status_code": 200, "text": "validation-ok"},
        should_send=True,
        title="会员入场提醒",
    )

    second = attendance.record_event(
        known_draft(
            prefix=prefix,
            suffix="known-2",
            event_time=base_time + timedelta(minutes=10),
            person_ref_id=member_id,
            camera_person_id="3427976339944670",
        ),
        settings=dedup_settings,
    )
    assert second.inserted and not second.should_notify and second.notification_suppressed
    assert second.suppressed_reason == "known_person_2h_window"

    no_dedup_settings = replace(settings, attendance_notify_dedup_enabled=False)
    third = attendance.record_event(
        known_draft(
            prefix=prefix,
            suffix="known-3",
            event_time=base_time + timedelta(minutes=20),
            person_ref_id=member_id,
            camera_person_id="3427976339944670",
        ),
        settings=no_dedup_settings,
    )
    assert third.inserted and third.should_notify and not third.notification_suppressed

    stranger = attendance.record_event(
        stranger_draft(
            prefix=prefix,
            suffix="stranger-1",
            event_time=base_time + timedelta(minutes=30),
        ),
        settings=settings,
    )
    assert stranger.inserted and stranger.should_notify and not stranger.notification_suppressed

    class_member = attendance.record_event(
        known_draft(
            prefix=prefix,
            suffix="class-member-1",
            event_time=base_time + timedelta(minutes=40),
            person_ref_id=class_member_id,
            camera_person_id="2026070501",
            person_type="class_member",
            name="验证上课会员",
            face_group_id="validation-class-members",
            face_group_name="上课会员",
        ),
        settings=dedup_settings,
    )
    assert class_member.inserted and class_member.should_notify and not class_member.notification_suppressed

    class_member_deduped = attendance.record_event(
        known_draft(
            prefix=prefix,
            suffix="class-member-2",
            event_time=base_time + timedelta(minutes=50),
            person_ref_id=class_member_id,
            camera_person_id="2026070501",
            person_type="class_member",
            name="验证上课会员",
            face_group_id="validation-class-members",
            face_group_name="上课会员",
        ),
        settings=dedup_settings,
    )
    assert class_member_deduped.inserted and not class_member_deduped.should_notify
    assert class_member_deduped.notification_suppressed
    assert class_member_deduped.suppressed_reason == "known_person_2h_window"

    report = reports.generate_daily_report(
        VALIDATION_DATE,
        save_snapshot=True,
        send_feishu=False,
        settings=settings,
    )
    summary = report.summary
    assert summary["member_entries"] >= 3
    assert summary["class_member_entries"] >= 2
    assert summary["stranger_entries"] >= 1
    assert summary["notification_suppressed_count"] >= 2
    assert fetch_member_camera_person_id(member_id, settings) == "3427976339944670"
    assert fetch_class_member_camera_person_id(class_member_id, settings) == "2026070501"

    return {
        "first_known": first.to_dict(),
        "second_known_deduped": second.to_dict(),
        "third_known_no_dedup": third.to_dict(),
        "stranger": stranger.to_dict(),
        "class_member": class_member.to_dict(),
        "class_member_deduped": class_member_deduped.to_dict(),
        "daily_report": report.to_dict(),
    }


def known_draft(
    *,
    prefix: str,
    suffix: str,
    event_time: datetime,
    person_ref_id: str,
    camera_person_id: str | None,
    person_type: str = "member",
    name: str = "验证会员",
    face_group_id: str = "validation-members",
    face_group_name: str = "会员",
) -> attendance.AttendanceEventDraft:
    identity = identity_for(prefix=prefix, suffix=suffix, event_time=event_time)
    raw_file = raw_file_for(prefix, suffix)
    return attendance.build_known_draft(
        identity=identity,
        raw_file=raw_file,
        person_type=person_type,
        person_ref_id=person_ref_id,
        name=name,
        camera_person_id=camera_person_id,
        face_group_id=face_group_id,
        face_group_name=face_group_name,
        match_number=1,
    )


def stranger_draft(*, prefix: str, suffix: str, event_time: datetime) -> attendance.AttendanceEventDraft:
    identity = identity_for(prefix=prefix, suffix=suffix, event_time=event_time)
    raw_file = raw_file_for(prefix, suffix)
    return attendance.build_stranger_draft(
        identity=identity,
        raw_file=raw_file,
        stored_image=None,
        image_url=f"http://example.test/{prefix}/{suffix}.jpg",
        token_hash=f"{prefix}-{suffix}-token-hash",
        image_source="validation",
        match_number=0,
    )


def identity_for(*, prefix: str, suffix: str, event_time: datetime) -> event_store.EventIdentity:
    return event_store.EventIdentity(
        dedupe_key=f"{prefix}-{suffix}",
        operator="FaceReco",
        serial_number="validation-camera",
        event_id=f"{prefix}-{suffix}",
        picture_md5="",
        event_time=event_time.isoformat(),
        event_time_compact=event_time.strftime("%Y%m%d%H%M%S"),
        received_at=event_time,
        event_day=event_time.strftime("%Y-%m-%d"),
    )


def raw_file_for(prefix: str, suffix: str) -> event_store.StoredFile:
    path = Path(f"/tmp/{prefix}-{suffix}.json")
    return event_store.StoredFile(path=path, relative_path=path.name, byte_size=0)


def cleanup(prefix: str, settings: AttendanceDbSettings) -> None:
    with transaction(settings) as conn:
        event_ids = [
            row[0]
            for row in conn.execute(
                text("select event_id from attendance_events where event_dedupe_key like :prefix"),
                {"prefix": f"{prefix}%"},
            )
        ]
        if event_ids:
            conn.execute(
                text("delete from feishu_notifications where attendance_event_id = any(:event_ids)"),
                {"event_ids": event_ids},
            )
            conn.execute(
                text("delete from attendance_events where event_id = any(:event_ids)"),
                {"event_ids": event_ids},
            )
        conn.execute(text("delete from daily_attendance_reports where report_date = :report_date"), {"report_date": VALIDATION_DATE})
        conn.execute(text("delete from strangers where image_url like :prefix"), {"prefix": f"%/{prefix}/%"})
        conn.execute(text("delete from members where member_id like :prefix"), {"prefix": f"{prefix}%"})
        conn.execute(text("delete from class_members where class_member_id like :prefix"), {"prefix": f"{prefix}%"})


def fetch_member_camera_person_id(member_id: str, settings: AttendanceDbSettings) -> str | None:
    with transaction(settings) as conn:
        row = conn.execute(
            text("select camera_person_id from members where member_id = :member_id"),
            {"member_id": member_id},
        ).first()
    return str(row[0]) if row and row[0] is not None else None


def fetch_class_member_camera_person_id(class_member_id: str, settings: AttendanceDbSettings) -> str | None:
    with transaction(settings) as conn:
        row = conn.execute(
            text("select camera_person_id from class_members where class_member_id = :class_member_id"),
            {"class_member_id": class_member_id},
        ).first()
    return str(row[0]) if row and row[0] is not None else None


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
