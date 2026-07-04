"""Replay stored P6S background images through InsightFace recheck.

This script is intentionally read-only for business state: it reads existing
processing records and stored images, calls the local InsightFace recheck
service, and writes standalone reports to a caller-provided output directory.
It does not send Feishu messages, write attendance rows, update dedupe state,
or modify camera configuration.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import face_recheck
from app.services.event_store import EventIdentity

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_ROOT = Path(
    os.environ.get("P6S_EVENT_IMAGE_DIR", "/var/lib/camera-face-guard/p6s_events")
)


@dataclass(frozen=True)
class ReplayRecord:
    record_path: Path
    record: dict[str, Any]
    background_path: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay saved P6S FaceReco background images through InsightFace.",
    )
    parser.add_argument("--date", required=True, help="Event date, e.g. 2026-07-04.")
    parser.add_argument(
        "--root",
        default=str(DEFAULT_ROOT),
        help="P6S event store root. Defaults to P6S_EVENT_IMAGE_DIR or production root.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Report output directory. Defaults to /tmp/p6s-face-recheck-replay-<timestamp>.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional max event count.")
    parser.add_argument("--event-id", default="", help="Optional single event ID filter.")
    parser.add_argument(
        "--jsonl-only",
        action="store_true",
        help="Write summary.json and results.jsonl, but skip results.csv.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root).expanduser()
    output_dir = _output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    settings = face_recheck.FaceRecheckSettings.from_env()
    records = _load_replay_records(
        root=root,
        event_date=args.date,
        event_id_filter=args.event_id.strip(),
        limit=args.limit,
    )
    results = [
        _replay_record(item, settings=settings, event_date=args.date)
        for item in records
    ]
    summary = _build_summary(results, root=root, event_date=args.date, output_dir=output_dir)

    _write_json(output_dir / "summary.json", summary)
    _write_jsonl(output_dir / "results.jsonl", results)
    if not args.jsonl_only:
        _write_csv(output_dir / "results.csv", results)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def _output_dir(raw: str) -> Path:
    if raw.strip():
        return Path(raw).expanduser()
    timestamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d_%H%M%S")
    return Path(f"/tmp/p6s-face-recheck-replay-{timestamp}")


def _load_replay_records(
    *,
    root: Path,
    event_date: str,
    event_id_filter: str,
    limit: int,
) -> list[ReplayRecord]:
    records_dir = root / "records" / event_date
    if not records_dir.exists():
        raise FileNotFoundError(f"records_dir_missing:{records_dir}")

    items: list[ReplayRecord] = []
    for record_path in sorted(records_dir.glob("*.json")):
        record = _read_json(record_path)
        if str(record.get("operator") or "") != "FaceReco":
            continue
        if event_id_filter and str(record.get("event_id") or "") != event_id_filter:
            continue
        background = ((record.get("images") or {}).get("background") or {})
        if background.get("status") != "saved":
            continue
        background_path = _background_path(root, background)
        if background_path is None:
            continue
        items.append(
            ReplayRecord(
                record_path=record_path,
                record=record,
                background_path=background_path,
            )
        )
        if limit > 0 and len(items) >= limit:
            break
    return items


def _background_path(root: Path, background: dict[str, Any]) -> Path | None:
    storage_path = str(background.get("storage_path") or "").strip()
    if storage_path:
        return Path(storage_path)
    relative_path = str(background.get("relative_path") or "").strip()
    if relative_path:
        return root / relative_path
    return None


def _replay_record(
    item: ReplayRecord,
    *,
    settings: face_recheck.FaceRecheckSettings,
    event_date: str,
) -> dict[str, Any]:
    record = item.record
    matched_person = record.get("matched_person") or {}
    camera_person = _camera_person_for_recheck(record)
    identity = _identity_from_record(record, event_date=event_date)

    result = face_recheck.run_face_recheck(
        face_recheck.FaceRecheckInput(
            identity=identity,
            route_result=_route_result(record),
            camera_person=camera_person,
            primary_image_path=item.background_path,
            background_image_path=item.background_path,
            capture_image_path=None,
            background_view_url=None,
            capture_view_url=None,
        ),
        settings=settings,
    )
    recheck = result.to_dict()
    selected_face = recheck.get("selected_face") or {}
    gallery_match = recheck.get("gallery_match") or {}
    classification = _classify(record, recheck)

    return {
        "event_time": record.get("event_time") or "",
        "event_id": str(record.get("event_id") or ""),
        "device_sn": record.get("camera_serial_number") or "",
        "record_path": str(item.record_path),
        "background_path": str(item.background_path),
        "camera_result": record.get("result") or "",
        "camera_name": matched_person.get("name") or "",
        "camera_id": _first_text(
            matched_person.get("id"),
            matched_person.get("person_id"),
            matched_person.get("camera_person_id"),
        ),
        "camera_role": _first_text(
            matched_person.get("person_role_name"),
            matched_person.get("person_role"),
        ),
        "recheck_status": recheck.get("status") or "",
        "recheck_reason": recheck.get("reason") or "",
        "face_count": recheck.get("face_count", 0),
        "quality_flags": selected_face.get("quality_flags") or [],
        "det_score": selected_face.get("det_score"),
        "face_size": _face_size(selected_face),
        "blur_score": selected_face.get("blur_score"),
        "frontal_score": selected_face.get("frontal_score"),
        "gallery_accepted": gallery_match.get("accepted"),
        "gallery_name": gallery_match.get("name") or "",
        "gallery_person_id": gallery_match.get("person_id") or "",
        "gallery_person_type": gallery_match.get("person_type") or "",
        "gallery_group_name": gallery_match.get("group_name") or "",
        "gallery_similarity": gallery_match.get("similarity"),
        "gallery_second_similarity": gallery_match.get("second_similarity"),
        "gallery_camera_identity_status": gallery_match.get("camera_identity_status") or "",
        "gallery_top5_candidates": gallery_match.get("candidates") or [],
        "classification": classification,
        "face_recheck": recheck,
    }


def _identity_from_record(record: dict[str, Any], *, event_date: str) -> EventIdentity:
    event_time = str(record.get("event_time") or "")
    received_at = _parse_datetime(record.get("received_at")) or datetime.now(LOCAL_TZ)
    compact = _compact_event_time(event_time, received_at)
    return EventIdentity(
        dedupe_key=str(record.get("dedupe_key") or f"replay-{record.get('event_id', '')}"),
        operator="FaceReco",
        serial_number=str(record.get("camera_serial_number") or ""),
        event_id=str(record.get("event_id") or ""),
        picture_md5="",
        event_time=event_time,
        event_time_compact=compact,
        received_at=received_at,
        event_day=event_date,
    )


def _camera_person_for_recheck(record: dict[str, Any]) -> dict[str, Any] | None:
    if record.get("result") != "known":
        return None
    person = record.get("matched_person") or {}
    if not person:
        return None
    return {
        "name": person.get("name") or "",
        "id": _first_text(person.get("id"), person.get("camera_person_id")),
        "person_id": _first_text(person.get("person_id"), person.get("id")),
        "camera_person_id": person.get("camera_person_id") or "",
        "role": person.get("person_role") or "",
        "role_name": person.get("person_role_name") or "",
        "credential_no": _first_text(person.get("credential_no"), person.get("id")),
    }


def _route_result(record: dict[str, Any]) -> str:
    result = str(record.get("result") or "")
    if result in {"known", "stranger", "parse_error"}:
        return result
    return "stranger"


def _classify(record: dict[str, Any], recheck: dict[str, Any]) -> str:
    camera_result = str(record.get("result") or "")
    status = str(recheck.get("status") or "")
    gallery = recheck.get("gallery_match") or {}
    accepted = gallery.get("accepted") is True
    identity_status = str(gallery.get("camera_identity_status") or "")

    if accepted and identity_status == "identity_conflict":
        return "identity_conflict"
    if camera_result == "known" and accepted and identity_status in {
        "name_matched",
        "id_matched",
        "name_and_id_matched",
    }:
        return "same_person"
    if camera_result == "known" and status == "filtered":
        return "camera_hit_but_recheck_filtered"
    if camera_result != "known" and accepted:
        return "camera_missed_but_gallery_hit"
    return "both_unknown_or_filtered"


def _build_summary(
    results: list[dict[str, Any]],
    *,
    root: Path,
    event_date: str,
    output_dir: Path,
) -> dict[str, Any]:
    status_counts = Counter(str(row.get("recheck_status") or "unknown") for row in results)
    class_counts = Counter(str(row.get("classification") or "unknown") for row in results)
    reason_counts = Counter(str(row.get("recheck_reason") or "unknown") for row in results)
    camera_counts = Counter(str(row.get("camera_result") or "unknown") for row in results)
    accepted_count = sum(1 for row in results if row.get("gallery_accepted") is True)
    conflict_count = class_counts.get("identity_conflict", 0)
    return {
        "generated_at": datetime.now(LOCAL_TZ).isoformat(),
        "event_date": event_date,
        "root": str(root),
        "output_dir": str(output_dir),
        "total": len(results),
        "passed": status_counts.get("passed", 0),
        "filtered": status_counts.get("filtered", 0),
        "error": status_counts.get("error", 0),
        "skipped": status_counts.get("skipped", 0),
        "accepted": accepted_count,
        "identity_conflict": conflict_count,
        "camera_unknown": camera_counts.get("stranger", 0),
        "camera_known": camera_counts.get("known", 0),
        "camera_known_insightface_same": class_counts.get("same_person", 0),
        "camera_known_insightface_diff": class_counts.get("identity_conflict", 0),
        "classification_counts": dict(sorted(class_counts.items())),
        "recheck_status_counts": dict(sorted(status_counts.items())),
        "camera_result_counts": dict(sorted(camera_counts.items())),
        "reason_counts": dict(reason_counts.most_common()),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "event_time",
        "event_id",
        "device_sn",
        "camera_result",
        "camera_name",
        "camera_id",
        "camera_role",
        "recheck_status",
        "recheck_reason",
        "face_count",
        "quality_flags",
        "det_score",
        "face_size",
        "blur_score",
        "frontal_score",
        "gallery_accepted",
        "gallery_name",
        "gallery_person_id",
        "gallery_person_type",
        "gallery_group_name",
        "gallery_similarity",
        "gallery_second_similarity",
        "gallery_camera_identity_status",
        "gallery_top5_candidates",
        "classification",
        "record_path",
        "background_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: _csv_value(row.get(key))
                    for key in fieldnames
                }
            )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ)
    return parsed.astimezone(LOCAL_TZ)


def _compact_event_time(event_time: str, fallback: datetime) -> str:
    parsed = _parse_datetime(event_time)
    if parsed is None:
        parsed = fallback
    return parsed.astimezone(LOCAL_TZ).strftime("%Y%m%d%H%M%S")


def _face_size(selected_face: dict[str, Any]) -> str:
    width = selected_face.get("width")
    height = selected_face.get("height")
    if width is None or height is None:
        return ""
    return f"{width}x{height}"


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


if __name__ == "__main__":
    main()
