"""Backfill recognition monitor rows from stored P6S processing records."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db import recognition_repo
from app.services import event_store, recognition_monitor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill recognition_events from processing records.")
    parser.add_argument("--root", default="", help="P6S event store root. Defaults to P6S_EVENT_IMAGE_DIR.")
    parser.add_argument("--date", default="", help="Single date, YYYY-MM-DD.")
    parser.add_argument("--date-from", default="", help="Start date, YYYY-MM-DD.")
    parser.add_argument("--date-to", default="", help="End date, YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max FaceReco records.")
    parser.add_argument("--apply", action="store_true", help="Write rows to recognition_events.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = event_store.event_store_root(args.root or None)
    record_files = _record_files(
        root=root,
        date_text=args.date.strip(),
        date_from=args.date_from.strip(),
        date_to=args.date_to.strip(),
    )
    summary = _backfill(record_files, root=root, apply=args.apply, limit=max(0, args.limit))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def _record_files(*, root: Path, date_text: str, date_from: str, date_to: str) -> list[Path]:
    records_root = root / "records"
    if date_text:
        dates = [date.fromisoformat(date_text)]
    elif date_from or date_to:
        start = date.fromisoformat(date_from)
        end = date.fromisoformat(date_to or date_from)
        if end < start:
            raise ValueError("--date-to must be >= --date-from")
        dates = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
    else:
        dates = sorted(
            date.fromisoformat(path.name)
            for path in records_root.iterdir()
            if path.is_dir() and _is_iso_date(path.name)
        ) if records_root.exists() else []

    files: list[Path] = []
    for item in dates:
        day_dir = records_root / item.isoformat()
        if day_dir.exists():
            files.extend(sorted(day_dir.glob("*.json")))
    return files


def _backfill(
    record_files: list[Path],
    *,
    root: Path,
    apply: bool,
    limit: int,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "apply": apply,
        "root": str(root),
        "scanned": 0,
        "face_reco": 0,
        "prepared": 0,
        "upserted": 0,
        "skipped_non_face_reco": 0,
        "parse_error_count": 0,
        "failed_count": 0,
        "errors": [],
    }
    rows: list[dict[str, Any]] = []
    for record_path in record_files:
        if limit and summary["face_reco"] >= limit:
            break
        summary["scanned"] += 1
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except Exception as exc:
            summary["parse_error_count"] += 1
            _append_error(summary, record_path, type(exc).__name__)
            continue
        if record.get("operator") != "FaceReco":
            summary["skipped_non_face_reco"] += 1
            continue
        summary["face_reco"] += 1
        try:
            row = recognition_monitor.build_event_row(
                record,
                record_path=record_path,
                root=root,
                ensure_crop=apply,
            )
        except Exception as exc:
            summary["failed_count"] += 1
            _append_error(summary, record_path, type(exc).__name__)
            continue
        rows.append(row)
        summary["prepared"] += 1

    if apply and rows:
        if not recognition_repo.database_url_configured():
            raise RuntimeError("DATABASE_URL is required when --apply is used")
        with recognition_repo.transaction() as conn:
            for row in rows:
                recognition_repo.upsert_recognition_event(conn, row)
                summary["upserted"] += 1
    return summary


def _append_error(summary: dict[str, Any], path: Path, error_type: str) -> None:
    if len(summary["errors"]) >= 20:
        return
    summary["errors"].append({"path": str(path), "error_type": error_type})


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    main()
