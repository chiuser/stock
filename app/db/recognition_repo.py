"""Repository helpers for recognition monitor rows."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any, Iterator, Mapping

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.db.config import normalize_database_url


_ENGINE: Engine | None = None
_ENGINE_KEY: tuple[str, int, bool] | None = None


def database_url_configured() -> bool:
    return bool(os.environ.get("DATABASE_URL", "").strip())


@contextmanager
def transaction() -> Iterator[Connection]:
    engine = _get_engine()
    with engine.begin() as conn:
        yield conn


def upsert_recognition_event(conn: Connection, values: Mapping[str, Any]) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            insert into recognition_events (
              event_dedupe_key,
              event_date,
              event_time,
              received_at,
              camera_serial_number,
              camera_event_id,
              operator,
              camera_result,
              camera_person_name,
              camera_person_id,
              camera_person_role,
              camera_person_role_name,
              recheck_status,
              recheck_reason,
              face_count,
              accepted_face_count,
              camera_target_face_status,
              has_identity_conflict,
              quality_flags,
              det_score,
              face_width,
              face_height,
              blur_score,
              frontal_score,
              gallery_accepted,
              gallery_name,
              gallery_person_id,
              gallery_person_type,
              gallery_group_name,
              gallery_similarity,
              gallery_second_similarity,
              gallery_camera_identity_status,
              gallery_top5_candidates,
              classification,
              background_relative_path,
              background_content_type,
              capture_relative_path,
              capture_content_type,
              insightface_crop_relative_path,
              insightface_crop_content_type,
              record_relative_path,
              raw_relative_path,
              face_recheck,
              final_recognition_decision,
              thresholds,
              updated_at
            ) values (
              :event_dedupe_key,
              :event_date,
              :event_time,
              :received_at,
              :camera_serial_number,
              :camera_event_id,
              :operator,
              :camera_result,
              :camera_person_name,
              :camera_person_id,
              :camera_person_role,
              :camera_person_role_name,
              :recheck_status,
              :recheck_reason,
              :face_count,
              :accepted_face_count,
              :camera_target_face_status,
              :has_identity_conflict,
              cast(:quality_flags as jsonb),
              :det_score,
              :face_width,
              :face_height,
              :blur_score,
              :frontal_score,
              :gallery_accepted,
              :gallery_name,
              :gallery_person_id,
              :gallery_person_type,
              :gallery_group_name,
              :gallery_similarity,
              :gallery_second_similarity,
              :gallery_camera_identity_status,
              cast(:gallery_top5_candidates as jsonb),
              :classification,
              :background_relative_path,
              :background_content_type,
              :capture_relative_path,
              :capture_content_type,
              :insightface_crop_relative_path,
              :insightface_crop_content_type,
              :record_relative_path,
              :raw_relative_path,
              cast(:face_recheck as jsonb),
              cast(:final_recognition_decision as jsonb),
              cast(:thresholds as jsonb),
              now()
            )
            on conflict (event_dedupe_key) do update set
              event_date = excluded.event_date,
              event_time = excluded.event_time,
              received_at = excluded.received_at,
              camera_serial_number = excluded.camera_serial_number,
              camera_event_id = excluded.camera_event_id,
              operator = excluded.operator,
              camera_result = excluded.camera_result,
              camera_person_name = excluded.camera_person_name,
              camera_person_id = excluded.camera_person_id,
              camera_person_role = excluded.camera_person_role,
              camera_person_role_name = excluded.camera_person_role_name,
              recheck_status = excluded.recheck_status,
              recheck_reason = excluded.recheck_reason,
              face_count = excluded.face_count,
              accepted_face_count = excluded.accepted_face_count,
              camera_target_face_status = excluded.camera_target_face_status,
              has_identity_conflict = excluded.has_identity_conflict,
              quality_flags = excluded.quality_flags,
              det_score = excluded.det_score,
              face_width = excluded.face_width,
              face_height = excluded.face_height,
              blur_score = excluded.blur_score,
              frontal_score = excluded.frontal_score,
              gallery_accepted = excluded.gallery_accepted,
              gallery_name = excluded.gallery_name,
              gallery_person_id = excluded.gallery_person_id,
              gallery_person_type = excluded.gallery_person_type,
              gallery_group_name = excluded.gallery_group_name,
              gallery_similarity = excluded.gallery_similarity,
              gallery_second_similarity = excluded.gallery_second_similarity,
              gallery_camera_identity_status = excluded.gallery_camera_identity_status,
              gallery_top5_candidates = excluded.gallery_top5_candidates,
              classification = excluded.classification,
              background_relative_path = excluded.background_relative_path,
              background_content_type = excluded.background_content_type,
              capture_relative_path = excluded.capture_relative_path,
              capture_content_type = excluded.capture_content_type,
              insightface_crop_relative_path = excluded.insightface_crop_relative_path,
              insightface_crop_content_type = excluded.insightface_crop_content_type,
              record_relative_path = excluded.record_relative_path,
              raw_relative_path = excluded.raw_relative_path,
              face_recheck = excluded.face_recheck,
              final_recognition_decision = excluded.final_recognition_decision,
              thresholds = excluded.thresholds,
              updated_at = now()
            returning recognition_event_id;
            """
        ),
        _params(values),
    ).mappings().first()
    return dict(row) if row else None


def upsert_recognition_event_faces(
    conn: Connection,
    *,
    recognition_event_id: int,
    rows: list[Mapping[str, Any]],
) -> int:
    """Upsert per-face recognition rows for one recognition event."""
    if not rows:
        return 0
    count = 0
    for row in rows:
        conn.execute(
            text(
                """
                insert into recognition_event_faces (
                  recognition_event_id,
                  image_source,
                  face_index,
                  face_key,
                  bbox,
                  center_x,
                  center_y,
                  face_width,
                  face_height,
                  det_score,
                  blur_score,
                  frontal_score,
                  quality_flags,
                  recheck_status,
                  recheck_reason,
                  gallery_accepted,
                  gallery_name,
                  gallery_person_id,
                  gallery_person_type,
                  gallery_group_name,
                  gallery_similarity,
                  gallery_second_similarity,
                  gallery_camera_identity_status,
                  gallery_top5_candidates,
                  business_action,
                  suppress_reason,
                  crop_relative_path,
                  crop_content_type,
                  updated_at
                ) values (
                  :recognition_event_id,
                  :image_source,
                  :face_index,
                  :face_key,
                  cast(:bbox as jsonb),
                  :center_x,
                  :center_y,
                  :face_width,
                  :face_height,
                  :det_score,
                  :blur_score,
                  :frontal_score,
                  cast(:quality_flags as jsonb),
                  :recheck_status,
                  :recheck_reason,
                  :gallery_accepted,
                  :gallery_name,
                  :gallery_person_id,
                  :gallery_person_type,
                  :gallery_group_name,
                  :gallery_similarity,
                  :gallery_second_similarity,
                  :gallery_camera_identity_status,
                  cast(:gallery_top5_candidates as jsonb),
                  :business_action,
                  :suppress_reason,
                  :crop_relative_path,
                  :crop_content_type,
                  now()
                )
                on conflict (recognition_event_id, image_source, face_index) do update set
                  face_key = excluded.face_key,
                  bbox = excluded.bbox,
                  center_x = excluded.center_x,
                  center_y = excluded.center_y,
                  face_width = excluded.face_width,
                  face_height = excluded.face_height,
                  det_score = excluded.det_score,
                  blur_score = excluded.blur_score,
                  frontal_score = excluded.frontal_score,
                  quality_flags = excluded.quality_flags,
                  recheck_status = excluded.recheck_status,
                  recheck_reason = excluded.recheck_reason,
                  gallery_accepted = excluded.gallery_accepted,
                  gallery_name = excluded.gallery_name,
                  gallery_person_id = excluded.gallery_person_id,
                  gallery_person_type = excluded.gallery_person_type,
                  gallery_group_name = excluded.gallery_group_name,
                  gallery_similarity = excluded.gallery_similarity,
                  gallery_second_similarity = excluded.gallery_second_similarity,
                  gallery_camera_identity_status = excluded.gallery_camera_identity_status,
                  gallery_top5_candidates = excluded.gallery_top5_candidates,
                  business_action = excluded.business_action,
                  suppress_reason = excluded.suppress_reason,
                  crop_relative_path = excluded.crop_relative_path,
                  crop_content_type = excluded.crop_content_type,
                  updated_at = now();
                """
            ),
            _face_params(recognition_event_id=recognition_event_id, values=row),
        )
        count += 1
    return count


def delete_stale_faces_for_event(
    conn: Connection,
    *,
    recognition_event_id: int,
    keep_keys: list[str],
) -> int:
    """Remove face rows that no longer exist after a replay/upsert."""
    if keep_keys:
        result = conn.execute(
            text(
                """
                delete from recognition_event_faces
                where recognition_event_id = :recognition_event_id
                  and face_key not in :keep_keys;
                """
            ).bindparams(bindparam("keep_keys", expanding=True)),
            {"recognition_event_id": recognition_event_id, "keep_keys": keep_keys},
        )
    else:
        result = conn.execute(
            text(
                """
                delete from recognition_event_faces
                where recognition_event_id = :recognition_event_id;
                """
            ),
            {"recognition_event_id": recognition_event_id},
        )
    return int(result.rowcount or 0)


def list_recognition_event_faces(
    conn: Connection,
    *,
    recognition_event_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            select *
            from recognition_event_faces
            where recognition_event_id = :recognition_event_id
            order by
              case image_source when 'background' then 0 when 'capture' then 1 else 2 end,
              face_index asc;
            """
        ),
        {"recognition_event_id": recognition_event_id},
    ).mappings()
    return [dict(row) for row in rows]


def fetch_summary(conn: Connection, *, event_date: date) -> dict[str, Any]:
    total = conn.execute(
        text("select count(*) from recognition_events where event_date = :event_date"),
        {"event_date": event_date},
    ).scalar_one()
    return {
        "date": event_date.isoformat(),
        "total": int(total or 0),
        "classification_counts": _count_by(conn, event_date=event_date, column="classification"),
        "camera_result_counts": _count_by(conn, event_date=event_date, column="camera_result"),
        "recheck_status_counts": _count_by(conn, event_date=event_date, column="recheck_status"),
        "reason_counts": _count_by(conn, event_date=event_date, column="recheck_reason"),
    }


def list_events(
    conn: Connection,
    *,
    event_date: date,
    classification: str | None = None,
    camera_result: str | None = None,
    recheck_status: str | None = None,
    reason: str | None = None,
    person: str | None = None,
    person_type: str | None = None,
    accepted: bool | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict[str, Any]:
    filters, params = _event_filters(
        event_date=event_date,
        classification=classification,
        camera_result=camera_result,
        recheck_status=recheck_status,
        reason=reason,
        person=person,
        person_type=person_type,
        accepted=accepted,
    )
    params["limit"] = max(1, min(limit, 100))
    params["offset"] = max(0, offset)
    where_sql = " and ".join(filters)
    total = conn.execute(
        text(f"select count(*) from recognition_events where {where_sql}"),
        params,
    ).scalar_one()
    rows = conn.execute(
        text(
            f"""
            select *
            from recognition_events
            where {where_sql}
            order by event_time desc nulls last, recognition_event_id desc
            limit :limit offset :offset;
            """
        ),
        params,
    ).mappings()
    return {"total": int(total or 0), "items": [dict(row) for row in rows]}


def fetch_event(conn: Connection, *, event_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            select *
            from recognition_events
            where event_dedupe_key = :event_key;
            """
        ),
        {"event_key": event_key},
    ).mappings().first()
    return dict(row) if row else None


def fetch_quality_overview(
    conn: Connection,
    *,
    date_from: date,
    date_to: date,
    example_limit: int = 5,
) -> dict[str, Any]:
    """Return read-only quality aggregates for the monitor page."""
    if date_to < date_from:
        raise ValueError("date_to must be >= date_from")
    total = conn.execute(
        text(
            """
            select count(*)
            from recognition_events
            where event_date between :date_from and :date_to;
            """
        ),
        {"date_from": date_from, "date_to": date_to},
    ).scalar_one()
    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "total": int(total or 0),
        "by_day": _daily_quality_counts(conn, date_from=date_from, date_to=date_to),
        "classification_counts": _count_by_range(conn, date_from=date_from, date_to=date_to, column="classification"),
        "camera_result_counts": _count_by_range(conn, date_from=date_from, date_to=date_to, column="camera_result"),
        "recheck_status_counts": _count_by_range(conn, date_from=date_from, date_to=date_to, column="recheck_status"),
        "reason_counts": _count_by_range(conn, date_from=date_from, date_to=date_to, column="recheck_reason"),
        "attention_examples": {
            "identity_conflict": _example_events(
                conn,
                date_from=date_from,
                date_to=date_to,
                classification="identity_conflict",
                limit=example_limit,
            ),
            "camera_missed_but_gallery_hit": _example_events(
                conn,
                date_from=date_from,
                date_to=date_to,
                classification="camera_missed_but_gallery_hit",
                limit=example_limit,
            ),
            "camera_hit_but_recheck_filtered": _example_events(
                conn,
                date_from=date_from,
                date_to=date_to,
                classification="camera_hit_but_recheck_filtered",
                limit=example_limit,
            ),
        },
    }


def _get_engine() -> Engine:
    raw_url = os.environ.get("DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("DATABASE_URL is required for recognition monitor DB writes")
    timeout = _env_int("ATTENDANCE_DB_CONNECT_TIMEOUT_SECONDS", 3, minimum=1)
    echo = _env_bool("ATTENDANCE_SQL_ECHO", False)
    url = normalize_database_url(raw_url)
    key = (url, timeout, echo)

    global _ENGINE, _ENGINE_KEY
    if _ENGINE is not None and _ENGINE_KEY == key:
        return _ENGINE
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = create_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        connect_args={"connect_timeout": timeout},
    )
    _ENGINE_KEY = key
    return _ENGINE


def _count_by(conn: Connection, *, event_date: date, column: str) -> dict[str, int]:
    allowed = {"classification", "camera_result", "recheck_status", "recheck_reason"}
    if column not in allowed:
        raise ValueError(f"unsupported summary column: {column}")
    rows = conn.execute(
        text(
            f"""
            select coalesce({column}, '') as key, count(*) as count
            from recognition_events
            where event_date = :event_date
            group by coalesce({column}, '')
            order by count desc, key asc;
            """
        ),
        {"event_date": event_date},
    ).mappings()
    return {str(row["key"] or "unknown"): int(row["count"]) for row in rows}


def _count_by_range(conn: Connection, *, date_from: date, date_to: date, column: str) -> dict[str, int]:
    allowed = {"classification", "camera_result", "recheck_status", "recheck_reason"}
    if column not in allowed:
        raise ValueError(f"unsupported quality column: {column}")
    rows = conn.execute(
        text(
            f"""
            select coalesce({column}, '') as key, count(*) as count
            from recognition_events
            where event_date between :date_from and :date_to
            group by coalesce({column}, '')
            order by count desc, key asc;
            """
        ),
        {"date_from": date_from, "date_to": date_to},
    ).mappings()
    return {str(row["key"] or "unknown"): int(row["count"]) for row in rows}


def _daily_quality_counts(conn: Connection, *, date_from: date, date_to: date) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            select
              event_date,
              classification,
              recheck_status,
              recheck_reason,
              count(*) as count
            from recognition_events
            where event_date between :date_from and :date_to
            group by event_date, classification, recheck_status, recheck_reason
            order by event_date asc;
            """
        ),
        {"date_from": date_from, "date_to": date_to},
    ).mappings()
    by_date: dict[str, dict[str, Any]] = {}
    current = date_from
    while current <= date_to:
        key = current.isoformat()
        by_date[key] = {
            "date": key,
            "total": 0,
            "classification_counts": {},
            "recheck_status_counts": {},
            "reason_counts": {},
        }
        current += timedelta(days=1)
    for row in rows:
        key = row["event_date"].isoformat()
        bucket = by_date.setdefault(
            key,
            {
                "date": key,
                "total": 0,
                "classification_counts": {},
                "recheck_status_counts": {},
                "reason_counts": {},
            },
        )
        count = int(row["count"])
        bucket["total"] += count
        _add_count(bucket["classification_counts"], row["classification"], count)
        _add_count(bucket["recheck_status_counts"], row["recheck_status"], count)
        _add_count(bucket["reason_counts"], row["recheck_reason"], count)
    return [by_date[key] for key in sorted(by_date)]


def _example_events(
    conn: Connection,
    *,
    date_from: date,
    date_to: date,
    classification: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        text(
            """
            select *
            from recognition_events
            where event_date between :date_from and :date_to
              and classification = :classification
            order by event_time desc nulls last, recognition_event_id desc
            limit :limit;
            """
        ),
        {
            "date_from": date_from,
            "date_to": date_to,
            "classification": classification,
            "limit": max(1, min(limit, 20)),
        },
    ).mappings()
    return [dict(row) for row in rows]


def _add_count(target: dict[str, int], key: Any, count: int) -> None:
    normalized = str(key or "unknown")
    target[normalized] = int(target.get(normalized, 0)) + count


def _event_filters(
    *,
    event_date: date,
    classification: str | None,
    camera_result: str | None,
    recheck_status: str | None,
    reason: str | None,
    person: str | None,
    person_type: str | None,
    accepted: bool | None,
) -> tuple[list[str], dict[str, Any]]:
    filters = ["event_date = :event_date"]
    params: dict[str, Any] = {"event_date": event_date}
    if classification:
        filters.append("classification = :classification")
        params["classification"] = classification
    if camera_result:
        filters.append("camera_result = :camera_result")
        params["camera_result"] = camera_result
    if recheck_status:
        filters.append("recheck_status = :recheck_status")
        params["recheck_status"] = recheck_status
    if reason:
        filters.append("recheck_reason = :reason")
        params["reason"] = reason
    if accepted is not None:
        filters.append("accepted_face_count > 0" if accepted else "accepted_face_count = 0")
    if person_type:
        filters.append(
            """
            (
              gallery_person_type = :person_type
              or exists (
                select 1
                from recognition_event_faces ref
                where ref.recognition_event_id = recognition_events.recognition_event_id
                  and ref.gallery_person_type = :person_type
              )
            )
            """
        )
        params["person_type"] = person_type
    if person:
        filters.append(
            """
            (
              camera_person_name ilike :person
              or camera_person_id ilike :person
              or gallery_name ilike :person
              or gallery_person_id ilike :person
              or exists (
                select 1
                from recognition_event_faces ref
                where ref.recognition_event_id = recognition_events.recognition_event_id
                  and (
                    ref.gallery_name ilike :person
                    or ref.gallery_person_id ilike :person
                  )
              )
            )
            """
        )
        params["person"] = f"%{person}%"
    return filters, params


def _params(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "event_dedupe_key": values.get("event_dedupe_key"),
        "event_date": values.get("event_date"),
        "event_time": values.get("event_time"),
        "received_at": values.get("received_at"),
        "camera_serial_number": _text_or_none(values.get("camera_serial_number")),
        "camera_event_id": _text_or_none(values.get("camera_event_id")),
        "operator": _text_or_none(values.get("operator")) or "FaceReco",
        "camera_result": _text_or_none(values.get("camera_result")) or "unknown",
        "camera_person_name": _text_or_none(values.get("camera_person_name")),
        "camera_person_id": _text_or_none(values.get("camera_person_id")),
        "camera_person_role": _text_or_none(values.get("camera_person_role")),
        "camera_person_role_name": _text_or_none(values.get("camera_person_role_name")),
        "recheck_status": _text_or_none(values.get("recheck_status")) or "not_rechecked",
        "recheck_reason": _text_or_none(values.get("recheck_reason")),
        "face_count": int(values.get("face_count") or 0),
        "accepted_face_count": int(values.get("accepted_face_count") or 0),
        "camera_target_face_status": _text_or_none(values.get("camera_target_face_status")),
        "has_identity_conflict": bool(values.get("has_identity_conflict") or False),
        "quality_flags": _json(values.get("quality_flags"), default=[]),
        "det_score": _float_or_none(values.get("det_score")),
        "face_width": _float_or_none(values.get("face_width")),
        "face_height": _float_or_none(values.get("face_height")),
        "blur_score": _float_or_none(values.get("blur_score")),
        "frontal_score": _float_or_none(values.get("frontal_score")),
        "gallery_accepted": values.get("gallery_accepted"),
        "gallery_name": _text_or_none(values.get("gallery_name")),
        "gallery_person_id": _text_or_none(values.get("gallery_person_id")),
        "gallery_person_type": _text_or_none(values.get("gallery_person_type")),
        "gallery_group_name": _text_or_none(values.get("gallery_group_name")),
        "gallery_similarity": _float_or_none(values.get("gallery_similarity")),
        "gallery_second_similarity": _float_or_none(values.get("gallery_second_similarity")),
        "gallery_camera_identity_status": _text_or_none(values.get("gallery_camera_identity_status")),
        "gallery_top5_candidates": _json(values.get("gallery_top5_candidates"), default=[]),
        "classification": _text_or_none(values.get("classification")) or "both_unknown_or_filtered",
        "background_relative_path": _text_or_none(values.get("background_relative_path")),
        "background_content_type": _text_or_none(values.get("background_content_type")),
        "capture_relative_path": _text_or_none(values.get("capture_relative_path")),
        "capture_content_type": _text_or_none(values.get("capture_content_type")),
        "insightface_crop_relative_path": _text_or_none(values.get("insightface_crop_relative_path")),
        "insightface_crop_content_type": _text_or_none(values.get("insightface_crop_content_type")),
        "record_relative_path": _text_or_none(values.get("record_relative_path")),
        "raw_relative_path": _text_or_none(values.get("raw_relative_path")),
        "face_recheck": _json(values.get("face_recheck"), default={}),
        "final_recognition_decision": _json(values.get("final_recognition_decision"), default={}),
        "thresholds": _json(values.get("thresholds"), default={}),
    }


def _face_params(*, recognition_event_id: int, values: Mapping[str, Any]) -> dict[str, Any]:
    bbox = values.get("bbox")
    if not isinstance(bbox, list):
        bbox = []
    return {
        "recognition_event_id": recognition_event_id,
        "image_source": _text_or_none(values.get("image_source")) or "background",
        "face_index": int(values.get("face_index") or 0),
        "face_key": _text_or_none(values.get("face_key")) or "background:0",
        "bbox": _json(bbox, default=[]),
        "center_x": _float_or_none(values.get("center_x")),
        "center_y": _float_or_none(values.get("center_y")),
        "face_width": _float_or_none(values.get("face_width")),
        "face_height": _float_or_none(values.get("face_height")),
        "det_score": _float_or_none(values.get("det_score")),
        "blur_score": _float_or_none(values.get("blur_score")),
        "frontal_score": _float_or_none(values.get("frontal_score")),
        "quality_flags": _json(values.get("quality_flags"), default=[]),
        "recheck_status": _text_or_none(values.get("recheck_status")) or "filtered",
        "recheck_reason": _text_or_none(values.get("recheck_reason")),
        "gallery_accepted": values.get("gallery_accepted"),
        "gallery_name": _text_or_none(values.get("gallery_name")),
        "gallery_person_id": _text_or_none(values.get("gallery_person_id")),
        "gallery_person_type": _text_or_none(values.get("gallery_person_type")),
        "gallery_group_name": _text_or_none(values.get("gallery_group_name")),
        "gallery_similarity": _float_or_none(values.get("gallery_similarity")),
        "gallery_second_similarity": _float_or_none(values.get("gallery_second_similarity")),
        "gallery_camera_identity_status": _text_or_none(values.get("gallery_camera_identity_status")),
        "gallery_top5_candidates": _json(values.get("gallery_top5_candidates"), default=[]),
        "business_action": _text_or_none(values.get("business_action")),
        "suppress_reason": _text_or_none(values.get("suppress_reason")),
        "crop_relative_path": _text_or_none(values.get("crop_relative_path")),
        "crop_content_type": _text_or_none(values.get("crop_content_type")),
    }


def _json(value: Any, *, default: Any) -> str:
    payload = default if value is None else value
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value
