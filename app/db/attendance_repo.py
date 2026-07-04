"""Parameterized SQL repository for attendance records and reports."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection


KNOWN_PERSON_TABLES = {
    "member": ("members", "member_id"),
    "coach": ("coaches", "coach_id"),
    "staff": ("staff", "staff_id"),
}


def upsert_people(conn: Connection, person_type: str, people: Sequence[Mapping[str, Any]]) -> int:
    if not people:
        return 0
    table_name, id_column = _known_person_target(person_type)
    stmt = text(
        f"""
        insert into {table_name} (
          {id_column}, name, face_group_id, camera_person_id, is_active, updated_at
        ) values (
          :person_ref_id, :name, :face_group_id, :camera_person_id, true, now()
        )
        on conflict ({id_column}) do update set
          name = excluded.name,
          face_group_id = excluded.face_group_id,
          camera_person_id = excluded.camera_person_id,
          is_active = true,
          updated_at = now();
        """
    )
    conn.execute(stmt, [_known_person_params(person) for person in people])
    return len(people)


def upsert_known_person(
    conn: Connection,
    *,
    person_type: str,
    person_ref_id: str,
    name: str,
    face_group_id: str | None,
    camera_person_id: str | int | None,
    event_time: datetime,
) -> None:
    table_name, id_column = _known_person_target(person_type)
    stmt = text(
        f"""
        insert into {table_name} (
          {id_column}, name, face_group_id, camera_person_id, is_active, last_seen_at, updated_at
        ) values (
          :person_ref_id, :name, :face_group_id, :camera_person_id, true, :event_time, now()
        )
        on conflict ({id_column}) do update set
          name = excluded.name,
          face_group_id = excluded.face_group_id,
          camera_person_id = excluded.camera_person_id,
          last_seen_at = greatest(coalesce({table_name}.last_seen_at, excluded.last_seen_at), excluded.last_seen_at),
          updated_at = now();
        """
    )
    conn.execute(
        stmt,
        {
            "person_ref_id": person_ref_id,
            "name": name,
            "face_group_id": face_group_id,
            "camera_person_id": _camera_person_id_param(camera_person_id),
            "event_time": event_time,
        },
    )


def insert_stranger(
    conn: Connection,
    *,
    event_time: datetime,
    image_path: str | None,
    image_url: str | None,
    image_token_hash: str | None,
) -> int:
    row = conn.execute(
        text(
            """
            insert into strangers (
              first_seen_at, image_path, image_url, image_token_hash
            ) values (
              :event_time, :image_path, :image_url, :image_token_hash
            )
            returning stranger_id;
            """
        ),
        {
            "event_time": event_time,
            "image_path": image_path,
            "image_url": image_url,
            "image_token_hash": image_token_hash,
        },
    ).first()
    if row is None:
        raise RuntimeError("failed to insert stranger")
    return int(row[0])


def lock_known_person_dedup(conn: Connection, *, person_type: str, person_ref_id: str | None) -> None:
    conn.execute(
        text(
            """
            select pg_advisory_xact_lock(
              hashtext(:person_type || ':' || coalesce(:person_ref_id, ''))
            );
            """
        ),
        {"person_type": person_type, "person_ref_id": person_ref_id},
    )


def find_recent_notified_event(
    conn: Connection,
    *,
    person_type: str,
    person_ref_id: str,
    event_time: datetime,
    window_seconds: int,
) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            select event_id, event_time
            from attendance_events
            where person_type = :person_type
              and person_ref_id = :person_ref_id
              and person_type <> 'stranger'
              and should_notify = true
              and notification_suppressed = false
              and event_time >= (:event_time - (:window_seconds * interval '1 second'))
              and event_time < :event_time
            order by event_time desc
            limit 1;
            """
        ),
        {
            "person_type": person_type,
            "person_ref_id": person_ref_id,
            "event_time": event_time,
            "window_seconds": window_seconds,
        },
    ).mappings().first()
    return dict(row) if row else None


def insert_attendance_event(conn: Connection, values: Mapping[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            insert into attendance_events (
              event_dedupe_key,
              camera_serial_number,
              camera_event_id,
              event_time,
              received_at,
              person_type,
              person_ref_id,
              person_name,
              face_group_id,
              face_group_name,
              match_number,
              image_source,
              image_path,
              image_url,
              raw_event_path,
              should_notify,
              notification_suppressed,
              suppressed_reason,
              dedupe_reference_event_id
            ) values (
              :event_dedupe_key,
              :camera_serial_number,
              :camera_event_id,
              :event_time,
              :received_at,
              :person_type,
              :person_ref_id,
              :person_name,
              :face_group_id,
              :face_group_name,
              :match_number,
              :image_source,
              :image_path,
              :image_url,
              :raw_event_path,
              :should_notify,
              :notification_suppressed,
              :suppressed_reason,
              :dedupe_reference_event_id
            )
            on conflict (event_dedupe_key) do nothing
            returning event_id, delivery_count;
            """
        ),
        _attendance_event_params(values),
    ).mappings().first()
    return dict(row) if row else None


def increment_delivery_count(conn: Connection, *, event_dedupe_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            update attendance_events
            set delivery_count = delivery_count + 1,
                updated_at = now()
            where event_dedupe_key = :event_dedupe_key
            returning event_id, delivery_count;
            """
        ),
        {"event_dedupe_key": event_dedupe_key},
    ).mappings().first()
    return dict(row) if row else None


def insert_feishu_notification(conn: Connection, values: Mapping[str, Any]) -> int:
    row = conn.execute(
        text(
            """
            insert into feishu_notifications (
              attendance_event_id,
              should_send,
              send_status,
              title,
              suppressed_reason,
              response_status_code,
              response_text,
              sent_at
            ) values (
              :attendance_event_id,
              :should_send,
              :send_status,
              :title,
              :suppressed_reason,
              :response_status_code,
              :response_text,
              :sent_at
            )
            returning notification_id;
            """
        ),
        {
            "attendance_event_id": values.get("attendance_event_id"),
            "should_send": values.get("should_send"),
            "send_status": values.get("send_status"),
            "title": values.get("title"),
            "suppressed_reason": values.get("suppressed_reason"),
            "response_status_code": values.get("response_status_code"),
            "response_text": values.get("response_text"),
            "sent_at": values.get("sent_at"),
        },
    ).first()
    if row is None:
        raise RuntimeError("failed to insert Feishu notification")
    return int(row[0])


def aggregate_daily_summary(conn: Connection, *, day_start: datetime, day_end: datetime) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            select
              count(*) filter (where person_type = 'member') as member_entries,
              count(*) filter (where person_type = 'coach') as coach_entries,
              count(*) filter (where person_type = 'staff') as staff_entries,
              count(*) filter (where person_type = 'stranger') as stranger_entries,
              count(*) filter (where person_type = 'unknown_known') as unknown_known_entries,
              count(*) filter (
                where exists (
                  select 1
                  from feishu_notifications n
                  where n.attendance_event_id = attendance_events.event_id
                    and n.send_status = 'sent'
                )
              ) as notification_sent_count,
              count(*) filter (where notification_suppressed = true) as notification_suppressed_count
            from attendance_events
            where event_time >= :day_start
              and event_time < :day_end;
            """
        ),
        {"day_start": day_start, "day_end": day_end},
    ).mappings().one()
    return dict(row)


def fetch_daily_strangers(conn: Connection, *, day_start: datetime, day_end: datetime) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            select
              event_id,
              event_time,
              camera_serial_number,
              camera_event_id,
              image_url,
              image_path
            from attendance_events
            where person_type = 'stranger'
              and event_time >= :day_start
              and event_time < :day_end
            order by event_time asc, event_id asc;
            """
        ),
        {"day_start": day_start, "day_end": day_end},
    ).mappings()
    return [dict(row) for row in rows]


def upsert_daily_report(conn: Connection, values: Mapping[str, Any]) -> None:
    conn.execute(
        text(
            """
            insert into daily_attendance_reports (
              report_date,
              member_entries,
              coach_entries,
              staff_entries,
              stranger_entries,
              unknown_known_entries,
              notification_sent_count,
              notification_suppressed_count,
              stranger_items,
              generated_at,
              updated_at
            ) values (
              :report_date,
              :member_entries,
              :coach_entries,
              :staff_entries,
              :stranger_entries,
              :unknown_known_entries,
              :notification_sent_count,
              :notification_suppressed_count,
              cast(:stranger_items as jsonb),
              now(),
              now()
            )
            on conflict (report_date) do update set
              member_entries = excluded.member_entries,
              coach_entries = excluded.coach_entries,
              staff_entries = excluded.staff_entries,
              stranger_entries = excluded.stranger_entries,
              unknown_known_entries = excluded.unknown_known_entries,
              notification_sent_count = excluded.notification_sent_count,
              notification_suppressed_count = excluded.notification_suppressed_count,
              stranger_items = excluded.stranger_items,
              generated_at = now(),
              updated_at = now();
            """
        ),
        {
            "report_date": values.get("report_date"),
            "member_entries": values.get("member_entries", 0),
            "coach_entries": values.get("coach_entries", 0),
            "staff_entries": values.get("staff_entries", 0),
            "stranger_entries": values.get("stranger_entries", 0),
            "unknown_known_entries": values.get("unknown_known_entries", 0),
            "notification_sent_count": values.get("notification_sent_count", 0),
            "notification_suppressed_count": values.get("notification_suppressed_count", 0),
            "stranger_items": json.dumps(values.get("stranger_items", []), ensure_ascii=False),
        },
    )


def fetch_daily_report(conn: Connection, *, report_date: Any) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            select *
            from daily_attendance_reports
            where report_date = :report_date;
            """
        ),
        {"report_date": report_date},
    ).mappings().first()
    return dict(row) if row else None


def list_attendance_events(
    conn: Connection,
    *,
    day_start: datetime,
    day_end: datetime,
    person_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    filters = ["event_time >= :day_start", "event_time < :day_end"]
    params: dict[str, Any] = {
        "day_start": day_start,
        "day_end": day_end,
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }
    if person_type:
        filters.append("person_type = :person_type")
        params["person_type"] = person_type
    rows = conn.execute(
        text(
            f"""
            select *
            from attendance_events
            where {' and '.join(filters)}
            order by event_time desc, event_id desc
            limit :limit offset :offset;
            """
        ),
        params,
    ).mappings()
    return [dict(row) for row in rows]


def _known_person_target(person_type: str) -> tuple[str, str]:
    try:
        return KNOWN_PERSON_TABLES[person_type]
    except KeyError as exc:
        raise ValueError(f"unsupported known person_type: {person_type}") from exc


def _known_person_params(person: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "person_ref_id": person.get("person_ref_id"),
        "name": person.get("name"),
        "face_group_id": person.get("face_group_id"),
        "camera_person_id": _camera_person_id_param(person.get("camera_person_id")),
    }


def _camera_person_id_param(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _attendance_event_params(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_dedupe_key": values.get("event_dedupe_key"),
        "camera_serial_number": values.get("camera_serial_number"),
        "camera_event_id": values.get("camera_event_id"),
        "event_time": values.get("event_time"),
        "received_at": values.get("received_at"),
        "person_type": values.get("person_type"),
        "person_ref_id": values.get("person_ref_id"),
        "person_name": values.get("person_name"),
        "face_group_id": values.get("face_group_id"),
        "face_group_name": values.get("face_group_name"),
        "match_number": values.get("match_number"),
        "image_source": values.get("image_source"),
        "image_path": values.get("image_path"),
        "image_url": values.get("image_url"),
        "raw_event_path": values.get("raw_event_path"),
        "should_notify": values.get("should_notify"),
        "notification_suppressed": values.get("notification_suppressed", False),
        "suppressed_reason": values.get("suppressed_reason"),
        "dedupe_reference_event_id": values.get("dedupe_reference_event_id"),
    }
