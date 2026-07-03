"""Attendance domain service for P6S FaceReco events."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.db import attendance_repo
from app.db.config import AttendanceDbSettings
from app.db.session import AttendanceDbError, transaction
from app.services import event_store

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
ROLE_TO_PERSON_TYPE = {
    "members": "member",
    "member": "member",
    "coaches": "coach",
    "coach": "coach",
    "staff": "staff",
}


@dataclass(frozen=True)
class AttendancePerson:
    person_type: str
    person_ref_id: str | None
    name: str
    camera_person_id: int | None
    face_group_id: str | None
    face_group_name: str | None


@dataclass(frozen=True)
class AttendanceImage:
    source: str
    path: str | None
    url: str | None
    token_hash: str | None


@dataclass(frozen=True)
class AttendanceEventDraft:
    event_dedupe_key: str
    camera_serial_number: str
    camera_event_id: str
    event_time: datetime
    received_at: datetime
    person: AttendancePerson
    match_number: int | None
    image: AttendanceImage | None
    raw_event_path: str


@dataclass(frozen=True)
class NotifyDecision:
    should_notify: bool
    suppressed: bool
    suppressed_reason: str | None = None
    reference_event_id: int | None = None


@dataclass(frozen=True)
class AttendanceRecordResult:
    enabled: bool
    event_id: int | None
    inserted: bool
    delivery_count: int | None
    should_notify: bool
    notification_suppressed: bool
    suppressed_reason: str | None = None
    dedupe_reference_event_id: int | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "event_id": self.event_id,
            "inserted": self.inserted,
            "delivery_count": self.delivery_count,
            "should_notify": self.should_notify,
            "notification_suppressed": self.notification_suppressed,
            "suppressed_reason": self.suppressed_reason,
            "dedupe_reference_event_id": self.dedupe_reference_event_id,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def person_type_for_role(role_code: str) -> str:
    return ROLE_TO_PERSON_TYPE.get(role_code, "unknown_known")


def build_known_draft(
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    person_type: str,
    person_ref_id: str | None,
    name: str,
    camera_person_id: int | None,
    face_group_id: str | None,
    face_group_name: str | None,
    match_number: int | None,
    stored_image: event_store.StoredImage | None = None,
    image_url: str | None = None,
    token_hash: str | None = None,
    image_source: str = "",
) -> AttendanceEventDraft:
    image = _attendance_image(
        stored_image=stored_image,
        image_url=image_url,
        token_hash=token_hash,
        image_source=image_source,
    )
    return AttendanceEventDraft(
        event_dedupe_key=identity.dedupe_key,
        camera_serial_number=identity.serial_number,
        camera_event_id=identity.event_id,
        event_time=_identity_event_time(identity),
        received_at=identity.received_at,
        person=AttendancePerson(
            person_type=person_type,
            person_ref_id=person_ref_id,
            name=name,
            camera_person_id=camera_person_id,
            face_group_id=face_group_id,
            face_group_name=face_group_name,
        ),
        match_number=match_number,
        image=image,
        raw_event_path=str(raw_file.path),
    )


def build_stranger_draft(
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    stored_image: event_store.StoredImage | None,
    image_url: str | None,
    token_hash: str | None,
    image_source: str,
    match_number: int | None,
) -> AttendanceEventDraft:
    image = None
    if stored_image or image_url or image_source:
        image = AttendanceImage(
            source=image_source,
            path=str(stored_image.path) if stored_image else None,
            url=image_url,
            token_hash=token_hash,
        )
    return AttendanceEventDraft(
        event_dedupe_key=identity.dedupe_key,
        camera_serial_number=identity.serial_number,
        camera_event_id=identity.event_id,
        event_time=_identity_event_time(identity),
        received_at=identity.received_at,
        person=AttendancePerson(
            person_type="stranger",
            person_ref_id=None,
            name="陌生人",
            camera_person_id=None,
            face_group_id=None,
            face_group_name=None,
        ),
        match_number=match_number,
        image=image,
        raw_event_path=str(raw_file.path),
    )


def build_parse_error_draft(
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    match_number: int | None,
    stored_image: event_store.StoredImage | None = None,
    image_url: str | None = None,
    token_hash: str | None = None,
    image_source: str = "",
) -> AttendanceEventDraft:
    image = _attendance_image(
        stored_image=stored_image,
        image_url=image_url,
        token_hash=token_hash,
        image_source=image_source,
    )
    return AttendanceEventDraft(
        event_dedupe_key=identity.dedupe_key,
        camera_serial_number=identity.serial_number,
        camera_event_id=identity.event_id,
        event_time=_identity_event_time(identity),
        received_at=identity.received_at,
        person=AttendancePerson(
            person_type="unknown_known",
            person_ref_id=None,
            name="解析失败",
            camera_person_id=None,
            face_group_id=None,
            face_group_name=None,
        ),
        match_number=match_number,
        image=image,
        raw_event_path=str(raw_file.path),
    )


def safe_record_event(draft: AttendanceEventDraft) -> AttendanceRecordResult:
    try:
        return record_event(draft)
    except Exception as exc:
        return _fallback_result(exc)


def record_event(
    draft: AttendanceEventDraft,
    *,
    settings: AttendanceDbSettings | None = None,
) -> AttendanceRecordResult:
    cfg = settings or AttendanceDbSettings.from_env()
    if not cfg.attendance_db_enabled:
        raise AttendanceDbError("attendance database is disabled")

    with transaction(cfg) as conn:
        person_ref_id = draft.person.person_ref_id
        if draft.person.person_type in {"member", "coach", "staff"} and person_ref_id:
            attendance_repo.upsert_known_person(
                conn,
                person_type=draft.person.person_type,
                person_ref_id=person_ref_id,
                name=draft.person.name,
                face_group_id=draft.person.face_group_id,
                camera_person_id=draft.person.camera_person_id,
                event_time=draft.event_time,
            )
        elif draft.person.person_type == "stranger":
            person_ref_id = str(
                attendance_repo.insert_stranger(
                    conn,
                    event_time=draft.event_time,
                    image_path=draft.image.path if draft.image else None,
                    image_url=draft.image.url if draft.image else None,
                    image_token_hash=draft.image.token_hash if draft.image else None,
                )
            )

        decision = _notify_decision(conn, draft, person_ref_id, cfg)
        values = _attendance_event_values(draft, person_ref_id, decision)
        inserted = attendance_repo.insert_attendance_event(conn, values)
        if inserted:
            return AttendanceRecordResult(
                enabled=True,
                event_id=int(inserted["event_id"]),
                inserted=True,
                delivery_count=int(inserted["delivery_count"]),
                should_notify=decision.should_notify,
                notification_suppressed=decision.suppressed,
                suppressed_reason=decision.suppressed_reason,
                dedupe_reference_event_id=decision.reference_event_id,
            )

        duplicate = attendance_repo.increment_delivery_count(
            conn,
            event_dedupe_key=draft.event_dedupe_key,
        )
        return AttendanceRecordResult(
            enabled=True,
            event_id=int(duplicate["event_id"]) if duplicate else None,
            inserted=False,
            delivery_count=int(duplicate["delivery_count"]) if duplicate else None,
            should_notify=False,
            notification_suppressed=True,
            suppressed_reason="duplicate_event",
        )


def safe_increment_delivery_count(event_dedupe_key: str) -> dict[str, Any]:
    try:
        with transaction() as conn:
            result = attendance_repo.increment_delivery_count(conn, event_dedupe_key=event_dedupe_key)
            return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}


def safe_record_notification(
    record_result: AttendanceRecordResult,
    *,
    feishu_result: dict[str, Any],
    should_send: bool,
    title: str,
    suppressed_reason: str | None = None,
) -> dict[str, Any]:
    if not record_result.enabled or not record_result.event_id:
        return {"ok": True, "skipped": True, "reason": "attendance event not recorded"}
    try:
        status = _notification_status(feishu_result, should_send)
        with transaction() as conn:
            notification_id = attendance_repo.insert_feishu_notification(
                conn,
                {
                    "attendance_event_id": record_result.event_id,
                    "should_send": should_send,
                    "send_status": status,
                    "title": title,
                    "suppressed_reason": suppressed_reason,
                    "response_status_code": _response_status_code(feishu_result),
                    "response_text": _response_text(feishu_result),
                    "sent_at": datetime.now(timezone.utc) if status == "sent" else None,
                },
            )
        return {"ok": True, "notification_id": notification_id, "send_status": status}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error_message": str(exc)}


def _notify_decision(
    conn: Any,
    draft: AttendanceEventDraft,
    person_ref_id: str | None,
    settings: AttendanceDbSettings,
) -> NotifyDecision:
    if draft.person.person_type == "stranger":
        return NotifyDecision(should_notify=True, suppressed=False)
    if not settings.attendance_notify_dedup_enabled:
        return NotifyDecision(should_notify=True, suppressed=False)
    if not person_ref_id:
        return NotifyDecision(should_notify=True, suppressed=False)

    attendance_repo.lock_known_person_dedup(
        conn,
        person_type=draft.person.person_type,
        person_ref_id=person_ref_id,
    )
    recent = attendance_repo.find_recent_notified_event(
        conn,
        person_type=draft.person.person_type,
        person_ref_id=person_ref_id,
        event_time=draft.event_time,
        window_seconds=settings.attendance_notify_dedup_window_seconds,
    )
    if recent:
        return NotifyDecision(
            should_notify=False,
            suppressed=True,
            suppressed_reason="known_person_2h_window",
            reference_event_id=int(recent["event_id"]),
        )
    return NotifyDecision(should_notify=True, suppressed=False)


def _attendance_image(
    *,
    stored_image: event_store.StoredImage | None,
    image_url: str | None,
    token_hash: str | None,
    image_source: str,
) -> AttendanceImage | None:
    if not (stored_image or image_url or image_source):
        return None
    return AttendanceImage(
        source=image_source,
        path=str(stored_image.path) if stored_image else None,
        url=image_url,
        token_hash=token_hash,
    )


def _attendance_event_values(
    draft: AttendanceEventDraft,
    person_ref_id: str | None,
    decision: NotifyDecision,
) -> dict[str, Any]:
    return {
        "event_dedupe_key": draft.event_dedupe_key,
        "camera_serial_number": draft.camera_serial_number,
        "camera_event_id": draft.camera_event_id,
        "event_time": draft.event_time,
        "received_at": draft.received_at,
        "person_type": draft.person.person_type,
        "person_ref_id": person_ref_id,
        "person_name": draft.person.name,
        "face_group_id": draft.person.face_group_id,
        "face_group_name": draft.person.face_group_name,
        "match_number": draft.match_number,
        "image_source": draft.image.source if draft.image else None,
        "image_path": draft.image.path if draft.image else None,
        "image_url": draft.image.url if draft.image else None,
        "raw_event_path": draft.raw_event_path,
        "should_notify": decision.should_notify,
        "notification_suppressed": decision.suppressed,
        "suppressed_reason": decision.suppressed_reason,
        "dedupe_reference_event_id": decision.reference_event_id,
    }


def _fallback_result(exc: Exception) -> AttendanceRecordResult:
    return AttendanceRecordResult(
        enabled=False,
        event_id=None,
        inserted=False,
        delivery_count=None,
        should_notify=True,
        notification_suppressed=False,
        error_type=type(exc).__name__,
        error_message=str(exc),
    )


def _identity_event_time(identity: event_store.EventIdentity) -> datetime:
    value = identity.event_time or ""
    digits = re.sub(r"\D", "", value)
    if len(digits) >= 14:
        try:
            return datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=LOCAL_TZ)
        except ValueError:
            pass
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=LOCAL_TZ)
            return parsed
        except ValueError:
            pass
    return identity.received_at


def _notification_status(feishu_result: dict[str, Any], should_send: bool) -> str:
    if not should_send:
        return "suppressed"
    if feishu_result.get("ok"):
        return "sent"
    return "failed"


def _response_status_code(feishu_result: dict[str, Any]) -> int | None:
    value = feishu_result.get("status_code")
    if isinstance(value, int):
        return value
    for item in feishu_result.get("results") or []:
        status_code = item.get("status_code")
        if isinstance(status_code, int):
            return status_code
    return None


def _response_text(feishu_result: dict[str, Any]) -> str:
    text = feishu_result.get("text")
    if text is None:
        text = json.dumps(feishu_result, ensure_ascii=False, default=_json_default)
    return str(text)[:4000]


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)
