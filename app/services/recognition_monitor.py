"""Build and persist recognition monitor rows from P6S processing records."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from app.db import recognition_repo
from app.services import event_store, face_recheck

LOGGER = logging.getLogger(__name__)
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


ALLOWED_IMAGE_PREFIXES = ("faces", "strangers")


def build_event_row(
    record: Mapping[str, Any],
    *,
    record_path: Path | None = None,
    raw_path: Path | None = None,
    root: Path | str | None = None,
    ensure_crop: bool = False,
) -> dict[str, Any]:
    """Convert a stored processing record into a DB-safe recognition row."""
    event_time = _parse_datetime(record.get("event_time"))
    received_at = _parse_datetime(record.get("received_at"))
    event_date = _event_date(event_time, received_at, record_path)
    matched_person = _dict(record.get("matched_person"))
    face_recheck = _dict(record.get("face_recheck"))
    selected_face = _dict(face_recheck.get("selected_face"))
    gallery_match = _dict(face_recheck.get("gallery_match"))
    background = _image_record(record, "background")
    capture = _image_record(record, "capture")
    crop = _dict(record.get("insightface_crop"))
    if ensure_crop and not crop:
        crop = ensure_insightface_crop(record, root=root)
    dedupe_key = _first_text(record.get("dedupe_key"), record.get("event_dedupe_key"))
    if not dedupe_key:
        raise ValueError("recognition event missing dedupe key")

    return {
        "event_dedupe_key": dedupe_key,
        "event_date": event_date,
        "event_time": event_time,
        "received_at": received_at,
        "camera_serial_number": _text(record.get("camera_serial_number")),
        "camera_event_id": _text(record.get("event_id")),
        "operator": _text(record.get("operator")) or "FaceReco",
        "camera_result": _text(record.get("result")) or "unknown",
        "camera_person_name": _first_text(matched_person.get("name")),
        "camera_person_id": _first_text(
            matched_person.get("id"),
            matched_person.get("person_id"),
            matched_person.get("camera_person_id"),
        ),
        "camera_person_role": _text(matched_person.get("person_role")),
        "camera_person_role_name": _text(matched_person.get("person_role_name")),
        "recheck_status": _text(face_recheck.get("status")) or "not_rechecked",
        "recheck_reason": _text(face_recheck.get("reason")),
        "face_count": _int(face_recheck.get("face_count")),
        "accepted_face_count": _accepted_face_count(face_recheck),
        "camera_target_face_status": _text(face_recheck.get("camera_target_face_status")),
        "has_identity_conflict": _has_identity_conflict(face_recheck),
        "quality_flags": _list(selected_face.get("quality_flags")),
        "det_score": _float(selected_face.get("det_score")),
        "face_width": _float(selected_face.get("width")),
        "face_height": _float(selected_face.get("height")),
        "blur_score": _float(selected_face.get("blur_score")),
        "frontal_score": _float(selected_face.get("frontal_score")),
        "gallery_accepted": gallery_match.get("accepted") if "accepted" in gallery_match else None,
        "gallery_name": _text(gallery_match.get("name")),
        "gallery_person_id": _text(gallery_match.get("person_id")),
        "gallery_person_type": _text(gallery_match.get("person_type")),
        "gallery_group_name": _text(gallery_match.get("group_name")),
        "gallery_similarity": _float(gallery_match.get("similarity")),
        "gallery_second_similarity": _float(gallery_match.get("second_similarity")),
        "gallery_camera_identity_status": _text(gallery_match.get("camera_identity_status")),
        "gallery_top5_candidates": _list(gallery_match.get("candidates")),
        "classification": classify_event(record, face_recheck),
        "background_relative_path": _text(background.get("relative_path")),
        "background_content_type": _text(background.get("content_type")),
        "capture_relative_path": _text(capture.get("relative_path")),
        "capture_content_type": _text(capture.get("content_type")),
        "insightface_crop_relative_path": _text(crop.get("relative_path")),
        "insightface_crop_content_type": _text(crop.get("content_type")),
        "record_relative_path": _relative_path(record_path, root=root),
        "raw_relative_path": _relative_path(raw_path, root=root) or _inferred_raw_relative_path(record),
        "face_recheck": face_recheck,
        "thresholds": _dict(face_recheck.get("thresholds")),
    }


def build_event_face_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert face_recheck.faces into DB rows for recognition_event_faces."""
    face_recheck_payload = _dict(record.get("face_recheck"))
    rows: list[dict[str, Any]] = []
    for fallback_index, face in enumerate(_list(face_recheck_payload.get("faces"))):
        face_payload = _dict(face)
        selected = _dict(face_payload.get("selected_face"))
        gallery = _dict(face_payload.get("gallery_match"))
        crop = _dict(face_payload.get("crop"))
        bbox = _list(selected.get("bbox"))
        width = _float(selected.get("width"))
        height = _float(selected.get("height"))
        center_x, center_y = _bbox_center(bbox)
        rows.append(
            {
                "image_source": _text(face_payload.get("image_source")) or "background",
                "face_index": _int(face_payload.get("face_index") if "face_index" in face_payload else fallback_index),
                "face_key": _text(face_payload.get("face_key")) or f"background:{fallback_index}",
                "bbox": bbox,
                "center_x": center_x,
                "center_y": center_y,
                "face_width": width,
                "face_height": height,
                "det_score": _float(selected.get("det_score")),
                "blur_score": _float(selected.get("blur_score")),
                "frontal_score": _float(selected.get("frontal_score")),
                "quality_flags": _list(selected.get("quality_flags")),
                "recheck_status": _text(face_payload.get("status")) or "filtered",
                "recheck_reason": _text(face_payload.get("reason")),
                "gallery_accepted": gallery.get("accepted") if "accepted" in gallery else None,
                "gallery_name": _text(gallery.get("name")),
                "gallery_person_id": _text(gallery.get("person_id")),
                "gallery_person_type": _text(gallery.get("person_type")),
                "gallery_group_name": _text(gallery.get("group_name")),
                "gallery_similarity": _float(gallery.get("similarity")),
                "gallery_second_similarity": _float(gallery.get("second_similarity")),
                "gallery_camera_identity_status": _text(gallery.get("camera_identity_status")),
                "gallery_top5_candidates": _list(gallery.get("candidates")),
                "crop_relative_path": _text(crop.get("relative_path")) if crop.get("status") == "saved" else "",
                "crop_content_type": _text(crop.get("content_type")) if crop.get("status") == "saved" else "",
            }
        )
    return rows


def safe_upsert_processing_record_file(
    record_path: Path,
    *,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Best-effort monitor write that must never break the P6S event flow."""
    if not recognition_repo.database_url_configured():
        return {"ok": True, "skipped": True, "reason": "database_url_not_configured"}
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("operator") != "FaceReco":
            return {"ok": True, "skipped": True, "reason": "not_face_reco"}
        row = build_event_row(record, record_path=record_path, root=root, ensure_crop=True)
        face_rows = build_event_face_rows(record)
        with recognition_repo.transaction() as conn:
            result = recognition_repo.upsert_recognition_event(conn, row)
            recognition_event_id = result.get("recognition_event_id") if result else None
            upserted_faces = 0
            stale_deleted = 0
            if recognition_event_id:
                upserted_faces = recognition_repo.upsert_recognition_event_faces(
                    conn,
                    recognition_event_id=int(recognition_event_id),
                    rows=face_rows,
                )
                stale_deleted = recognition_repo.delete_stale_faces_for_event(
                    conn,
                    recognition_event_id=int(recognition_event_id),
                    keep_keys=[row["face_key"] for row in face_rows],
                )
        return {
            "ok": True,
            "skipped": False,
            "recognition_event_id": recognition_event_id,
            "face_rows_upserted": upserted_faces,
            "stale_face_rows_deleted": stale_deleted,
        }
    except Exception as exc:
        LOGGER.warning("recognition monitor upsert failed: %s", type(exc).__name__)
        return {"ok": False, "error_type": type(exc).__name__}


def classify_event(record: Mapping[str, Any], face_recheck: Mapping[str, Any] | None = None) -> str:
    camera_result = str(record.get("result") or "")
    recheck = _dict(face_recheck if face_recheck is not None else record.get("face_recheck"))
    status = str(recheck.get("status") or "")
    face_gallery_matches = _face_gallery_matches(recheck)

    if any(_accepted(match) and _text(match.get("camera_identity_status")) == "identity_conflict" for match in face_gallery_matches):
        return "identity_conflict"
    if camera_result == "known" and any(_accepted(match) and _identity_matched(match) for match in face_gallery_matches):
        return "same_person"
    if camera_result == "known" and status == "filtered":
        return "camera_hit_but_recheck_filtered"
    if camera_result != "known" and any(_accepted(match) for match in face_gallery_matches):
        return "camera_missed_but_gallery_hit"
    return "both_unknown_or_filtered"


def build_summary_response(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "date": _text(summary.get("date")),
        "total": _int(summary.get("total")),
        "classification_counts": _dict(summary.get("classification_counts")),
        "camera_result_counts": _dict(summary.get("camera_result_counts")),
        "recheck_status_counts": _dict(summary.get("recheck_status_counts")),
        "reason_counts": _dict(summary.get("reason_counts")),
    }


def build_events_response(
    *,
    event_date: date,
    page: int,
    page_size: int,
    total: int,
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "date": event_date.isoformat(),
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [row_to_event(row) for row in rows],
    }


def build_quality_response(overview: Mapping[str, Any]) -> dict[str, Any]:
    total = _int(overview.get("total"))
    classification_counts = _dict(overview.get("classification_counts"))
    recheck_status_counts = _dict(overview.get("recheck_status_counts"))
    return {
        "date_from": _text(overview.get("date_from")),
        "date_to": _text(overview.get("date_to")),
        "total": total,
        "rates": {
            "identity_conflict": _rate(classification_counts.get("identity_conflict"), total),
            "camera_missed_but_gallery_hit": _rate(classification_counts.get("camera_missed_but_gallery_hit"), total),
            "camera_hit_but_recheck_filtered": _rate(classification_counts.get("camera_hit_but_recheck_filtered"), total),
            "filtered": _rate(recheck_status_counts.get("filtered"), total),
        },
        "classification_counts": classification_counts,
        "camera_result_counts": _dict(overview.get("camera_result_counts")),
        "recheck_status_counts": recheck_status_counts,
        "reason_counts": _dict(overview.get("reason_counts")),
        "by_day": [_quality_day(day) for day in _list(overview.get("by_day"))],
        "attention_examples": {
            key: [row_to_event(row) for row in _list(rows)]
            for key, rows in _dict(overview.get("attention_examples")).items()
        },
    }


def row_to_event(
    row: Mapping[str, Any],
    *,
    include_detail: bool = False,
    faces: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    event = {
        "event_key": _text(row.get("event_dedupe_key")),
        "event_id": _text(row.get("camera_event_id")),
        "event_time": _iso_or_text(row.get("event_time")),
        "received_at": _iso_or_text(row.get("received_at")),
        "device_sn": _text(row.get("camera_serial_number")),
        "classification": _text(row.get("classification")),
        "camera": {
            "result": _text(row.get("camera_result")),
            "name": _text(row.get("camera_person_name")),
            "id": _text(row.get("camera_person_id")),
            "role": _text(row.get("camera_person_role")),
            "role_name": _text(row.get("camera_person_role_name")),
        },
        "recheck": {
            "status": _text(row.get("recheck_status")),
            "reason": _text(row.get("recheck_reason")),
            "face_count": _int(row.get("face_count")),
            "accepted_face_count": _int(row.get("accepted_face_count")),
            "camera_target_face_status": _text(row.get("camera_target_face_status")),
            "has_identity_conflict": bool(row.get("has_identity_conflict") or False),
            "quality_flags": _json_list(row.get("quality_flags")),
            "det_score": _float(row.get("det_score")),
            "face_size": _face_size(row),
            "blur_score": _float(row.get("blur_score")),
            "frontal_score": _float(row.get("frontal_score")),
        },
        "gallery": {
            "accepted": row.get("gallery_accepted"),
            "name": _text(row.get("gallery_name")),
            "person_id": _text(row.get("gallery_person_id")),
            "person_type": _text(row.get("gallery_person_type")),
            "group_name": _text(row.get("gallery_group_name")),
            "similarity": _float(row.get("gallery_similarity")),
            "second_similarity": _float(row.get("gallery_second_similarity")),
            "camera_identity_status": _text(row.get("gallery_camera_identity_status")),
            "top5_candidates": _json_list(row.get("gallery_top5_candidates")),
        },
        "images": {
            "background": _image_ref(row, "background"),
            "capture": _image_ref(row, "capture"),
            "insightface_crop": _image_ref(row, "insightface_crop"),
        },
    }
    if include_detail:
        event["faces"] = [face_row_to_event(face) for face in (faces or [])]
        event["record"] = {
            "record_relative_path": _text(row.get("record_relative_path")),
            "raw_relative_path": _text(row.get("raw_relative_path")),
            "face_recheck": _json_dict(row.get("face_recheck")),
            "thresholds": _json_dict(row.get("thresholds")),
        }
    return event


def face_row_to_event(row: Mapping[str, Any]) -> dict[str, Any]:
    bbox = _json_list(row.get("bbox"))
    crop_relative_path = _text(row.get("crop_relative_path"))
    return {
        "face_key": _text(row.get("face_key")),
        "image_source": _text(row.get("image_source")) or "background",
        "face_index": _int(row.get("face_index")),
        "bbox": bbox,
        "position_hint": _position_hint(row),
        "status": _text(row.get("recheck_status")),
        "reason": _text(row.get("recheck_reason")),
        "quality": {
            "det_score": _float(row.get("det_score")),
            "face_size": _face_size(row),
            "width": _float(row.get("face_width")),
            "height": _float(row.get("face_height")),
            "blur_score": _float(row.get("blur_score")),
            "frontal_score": _float(row.get("frontal_score")),
            "quality_flags": _json_list(row.get("quality_flags")),
        },
        "gallery": {
            "accepted": row.get("gallery_accepted"),
            "name": _text(row.get("gallery_name")),
            "person_id": _text(row.get("gallery_person_id")),
            "person_type": _text(row.get("gallery_person_type")),
            "group_name": _text(row.get("gallery_group_name")),
            "similarity": _float(row.get("gallery_similarity")),
            "second_similarity": _float(row.get("gallery_second_similarity")),
            "camera_identity_status": _text(row.get("gallery_camera_identity_status")),
            "top5_candidates": _json_list(row.get("gallery_top5_candidates")),
        },
        "crop": _crop_ref(crop_relative_path, _text(row.get("crop_content_type"))),
    }


def page_size_from_env() -> tuple[int, int]:
    return (
        _env_int("RECOGNITION_MONITOR_DEFAULT_PAGE_SIZE", 30, minimum=1),
        _env_int("RECOGNITION_MONITOR_MAX_PAGE_SIZE", 100, minimum=1),
    )


def validate_image_relative_path(relative_path: str) -> str:
    text = str(relative_path or "").strip()
    path = Path(text)
    if not text or path.is_absolute() or ".." in path.parts:
        raise ValueError("invalid image relative path")
    normalized = path.as_posix().strip("/")
    if not normalized:
        raise ValueError("empty image relative path")
    first_part = Path(normalized).parts[0] if Path(normalized).parts else ""
    if first_part not in ALLOWED_IMAGE_PREFIXES:
        raise ValueError("image path prefix is not allowed")
    return normalized


def resolve_image_path(relative_path: str, *, root: Path | str | None = None) -> tuple[Path, str]:
    normalized = validate_image_relative_path(relative_path)
    store_root = event_store.event_store_root(root)
    image_path = store_root / normalized
    event_store.relative_to_root(image_path, root=store_root)
    if not image_path.exists() or not image_path.is_file():
        raise FileNotFoundError("image file not found")
    return image_path, _content_type_for_path(image_path)


def ensure_insightface_crop(record: Mapping[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    selected_face = _dict(_dict(record.get("face_recheck")).get("selected_face"))
    bbox = selected_face.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 4:
        return {"status": "missing_bbox", "kind": "insightface_crop"}
    background = _image_record(record, "background")
    relative_path = _text(background.get("relative_path"))
    if not relative_path:
        return {"status": "missing_background", "kind": "insightface_crop"}
    try:
        background_path, _ = resolve_image_path(relative_path, root=root)
        crop_bytes = _crop_image(background_path, bbox)
        identity = _identity_from_record(record)
        stored = event_store.save_face_image(
            identity,
            crop_bytes,
            source="InsightFaceCrop",
            root=root,
            category="faces",
            image_kind="insightface_crop",
        )
        return stored.to_dict()
    except Exception as exc:
        return {
            "status": "crop_failed",
            "kind": "insightface_crop",
            "error": type(exc).__name__,
        }


def attach_face_crops_to_recheck(
    recheck_result: face_recheck.FaceRecheckResult,
    *,
    identity: event_store.EventIdentity,
    source_images: Mapping[str, event_store.StoredImage | Path | str | None],
    root: Path | str | None = None,
) -> face_recheck.FaceRecheckResult:
    """Save per-face InsightFace crops and attach safe summaries to the result."""
    crops: dict[str, face_recheck.FaceCropSummary] = {}
    for face in recheck_result.faces:
        if face.selected_face is None:
            continue
        image_path = _source_image_path(source_images.get(face.image_source))
        if image_path is None:
            crops[face.face_key] = face_recheck.FaceCropSummary(error_type="source_image_missing")
            continue
        try:
            crop_bytes = _crop_image(image_path, list(face.selected_face.bbox))
            stored = event_store.save_face_image(
                identity,
                crop_bytes,
                source="InsightFaceCrop",
                root=root,
                category="faces",
                image_kind=f"insightface_{face.image_source}_face{face.face_index}",
            )
            crops[face.face_key] = face_recheck.FaceCropSummary(
                relative_path=stored.relative_path,
                content_type=stored.content_type,
            )
        except Exception as exc:
            crops[face.face_key] = face_recheck.FaceCropSummary(error_type=type(exc).__name__)
    return face_recheck.with_face_crops(recheck_result, crops)


def rebuild_face_recheck_for_record(
    record: Mapping[str, Any],
    *,
    root: Path | str | None = None,
    save_crops: bool = True,
) -> face_recheck.FaceRecheckResult:
    """Run current InsightFace settings against stored record images without side effects beyond crop files."""
    background_path = _resolved_record_image_path(record, "background", root=root)
    capture_path = _resolved_record_image_path(record, "capture", root=root)
    identity = _identity_from_record(record)
    result = face_recheck.run_face_recheck(
        face_recheck.FaceRecheckInput(
            identity=identity,
            route_result=_route_result_from_record(record),
            camera_person=_camera_person_from_record(record),
            primary_image_path=background_path or capture_path,
            background_image_path=background_path,
            capture_image_path=capture_path,
            background_view_url=None,
            capture_view_url=None,
        )
    )
    if not save_crops:
        return result
    return attach_face_crops_to_recheck(
        result,
        identity=identity,
        source_images={"background": background_path, "capture": capture_path},
        root=root,
    )


def _image_record(record: Mapping[str, Any], key: str) -> dict[str, Any]:
    images = _dict(record.get("images"))
    image = _dict(images.get(key))
    if image:
        return image
    if key == "background" and _dict(record.get("image")).get("kind") == "background":
        return _dict(record.get("image"))
    if key == "capture" and _dict(record.get("image")).get("kind") == "capture":
        return _dict(record.get("image"))
    return {}


def _resolved_record_image_path(record: Mapping[str, Any], key: str, *, root: Path | str | None) -> Path | None:
    relative_path = _text(_image_record(record, key).get("relative_path"))
    if not relative_path:
        return None
    try:
        image_path, _ = resolve_image_path(relative_path, root=root)
    except Exception:
        return None
    return image_path


def _image_ref(row: Mapping[str, Any], kind: Literal["background", "capture", "insightface_crop"]) -> dict[str, Any]:
    relative_path = _text(row.get(f"{kind}_relative_path"))
    content_type = _text(row.get(f"{kind}_content_type"))
    if not relative_path:
        return {"status": "missing", "kind": kind}
    return {
        "status": "saved",
        "kind": kind,
        "relative_path": relative_path,
        "content_type": content_type or _content_type_for_path(Path(relative_path)),
        "api_url": f"/api/recognition-monitor/images?{urlencode({'relative_path': relative_path})}",
    }


def _crop_ref(relative_path: str, content_type: str) -> dict[str, Any]:
    if not relative_path:
        return {"status": "missing", "kind": "face_crop"}
    return {
        "status": "saved",
        "kind": "face_crop",
        "relative_path": relative_path,
        "content_type": content_type or _content_type_for_path(Path(relative_path)),
        "api_url": f"/api/recognition-monitor/images?{urlencode({'relative_path': relative_path})}",
    }


def _crop_image(image_path: Path, bbox: list[Any]) -> bytes:
    import cv2
    import numpy as np

    data = np.fromfile(str(image_path), dtype=np.uint8)
    if data.size == 0:
        raise ValueError("image_empty")
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("image_read_failed")
    height, width = img.shape[:2]
    x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    left = max(0, min(width, int(x1)))
    top = max(0, min(height, int(y1)))
    right = max(0, min(width, int(x2)))
    bottom = max(0, min(height, int(y2)))
    if right <= left or bottom <= top:
        raise ValueError("invalid_bbox")
    crop = img[top:bottom, left:right]
    ok, encoded = cv2.imencode(".jpg", crop)
    if not ok:
        raise ValueError("crop_encode_failed")
    return encoded.tobytes()


def _source_image_path(source: event_store.StoredImage | Path | str | None) -> Path | None:
    if source is None:
        return None
    if isinstance(source, event_store.StoredImage):
        return source.path
    return Path(source)


def _identity_from_record(record: Mapping[str, Any]) -> event_store.EventIdentity:
    received_at = _parse_datetime(record.get("received_at")) or datetime.now(LOCAL_TZ)
    event_time = _text(record.get("event_time"))
    return event_store.EventIdentity(
        dedupe_key=_first_text(record.get("dedupe_key"), record.get("event_dedupe_key")),
        operator=_text(record.get("operator")) or "FaceReco",
        serial_number=_text(record.get("camera_serial_number")) or "unknown",
        event_id=_text(record.get("event_id")),
        picture_md5="",
        event_time=event_time,
        event_time_compact=_compact_event_time(event_time, received_at),
        received_at=received_at,
        event_day=_event_date(_parse_datetime(event_time), received_at, None).isoformat(),
    )


def _route_result_from_record(record: Mapping[str, Any]) -> Literal["known", "stranger", "parse_error"]:
    result = _text(record.get("result"))
    if result == "known":
        return "known"
    if result == "parse_error":
        return "parse_error"
    return "stranger"


def _camera_person_from_record(record: Mapping[str, Any]) -> dict[str, Any] | None:
    matched = _dict(record.get("matched_person"))
    if not matched:
        return None
    return {
        "name": _text(matched.get("name")),
        "person_id": _first_text(matched.get("id"), matched.get("person_id"), matched.get("camera_person_id")),
        "id": _first_text(matched.get("id"), matched.get("person_id"), matched.get("camera_person_id")),
        "role": _text(matched.get("person_role")),
        "role_name": _text(matched.get("person_role_name")),
        "group_id": _text(matched.get("group_id")),
        "group_name": _text(matched.get("group_name")),
    }


def _relative_path(path: Path | None, *, root: Path | str | None) -> str | None:
    if path is None:
        return None
    try:
        return event_store.relative_to_root(path, root=root)
    except Exception:
        return None


def _inferred_raw_relative_path(record: Mapping[str, Any]) -> str | None:
    dedupe_key = _text(record.get("dedupe_key"))
    if not dedupe_key:
        return None
    event_date = _text(record.get("event_time"))[:10]
    if not event_date or len(event_date) != 10:
        received_at = _text(record.get("received_at"))[:10]
        event_date = received_at if len(received_at) == 10 else ""
    if not event_date:
        return None
    return f"raw/{event_date}/{dedupe_key}.json"


def _event_date(event_time: datetime | None, received_at: datetime | None, record_path: Path | None) -> date:
    for value in (event_time, received_at):
        if value is not None:
            return value.astimezone(LOCAL_TZ).date()
    if record_path is not None:
        try:
            return date.fromisoformat(record_path.parent.name)
        except ValueError:
            pass
    return datetime.now(LOCAL_TZ).date()


def _parse_datetime(value: Any) -> datetime | None:
    text = _text(value)
    if not text:
        return None
    normalized = text
    if len(normalized) == 19 and normalized[4] == "-" and normalized[13] == ":":
        normalized = normalized.replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _compact_event_time(event_time: str, fallback: datetime) -> str:
    parsed = _parse_datetime(event_time) or fallback
    return parsed.astimezone(LOCAL_TZ).strftime("%Y%m%d%H%M%S")


def _content_type_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    return "application/octet-stream"


def _face_size(row: Mapping[str, Any]) -> str:
    width = row.get("face_width")
    height = row.get("face_height")
    if width is None or height is None:
        return ""
    return f"{width}x{height}"


def _bbox_center(bbox: list[Any]) -> tuple[float | None, float | None]:
    if len(bbox) < 4:
        return None, None
    try:
        x1, y1, x2, y2 = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError):
        return None, None
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def _position_hint(row: Mapping[str, Any]) -> str:
    center_x = _float(row.get("center_x"))
    if center_x is None:
        return ""
    width = _float(row.get("face_width")) or 0.0
    left = center_x - (width / 2.0)
    if left < 320:
        return "left"
    if left > 640:
        return "right"
    return "center"


def _accepted(match: Mapping[str, Any]) -> bool:
    return match.get("accepted") is True


def _identity_matched(match: Mapping[str, Any]) -> bool:
    return _text(match.get("camera_identity_status")) in {
        "name_matched",
        "id_matched",
        "name_and_id_matched",
    }


def _accepted_face_count(face_recheck: Mapping[str, Any]) -> int:
    if "accepted_face_count" in face_recheck:
        return _int(face_recheck.get("accepted_face_count"))
    matches = _face_gallery_matches(face_recheck)
    return sum(1 for match in matches if _accepted(match))


def _has_identity_conflict(face_recheck: Mapping[str, Any]) -> bool:
    if face_recheck.get("has_identity_conflict") is True:
        return True
    return any(
        _accepted(match) and _text(match.get("camera_identity_status")) == "identity_conflict"
        for match in _face_gallery_matches(face_recheck)
    )


def _face_gallery_matches(face_recheck: Mapping[str, Any]) -> list[dict[str, Any]]:
    matches = [
        _dict(_dict(face).get("gallery_match"))
        for face in _list(face_recheck.get("faces"))
    ]
    matches = [match for match in matches if match]
    if not matches:
        legacy = _dict(face_recheck.get("gallery_match"))
        if legacy:
            matches = [legacy]
    return matches


def _quality_day(value: Any) -> dict[str, Any]:
    day = _dict(value)
    return {
        "date": _text(day.get("date")),
        "total": _int(day.get("total")),
        "classification_counts": _dict(day.get("classification_counts")),
        "recheck_status_counts": _dict(day.get("recheck_status_counts")),
        "reason_counts": _dict(day.get("reason_counts")),
    }


def _rate(value: Any, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(_int(value) / total, 4)


def _iso_or_text(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return _text(value)


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            payload = json.loads(value)
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            payload = json.loads(value)
        except ValueError:
            return []
        return payload if isinstance(payload, list) else []
    return []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
