"""Clean expired local P6S event-store day directories.

The script is intentionally local-only: it never talks to the camera, Feishu,
or the remote server. By default it prints a dry-run report; pass --apply to
delete expired day directories under raw/, records/, faces/, strangers/, and links/.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import event_store

EVENT_SUBDIRS = ("raw", "records", "faces", "strangers", "links")
DAY_FORMAT = "%Y-%m-%d"


@dataclass(frozen=True)
class CleanupTarget:
    subdir: str
    day: str
    path: Path
    files: int
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "subdir": self.subdir,
            "day": self.day,
            "path": str(self.path),
            "files": self.files,
            "bytes": self.bytes,
        }


def main() -> int:
    args = parse_args()
    root = event_store.event_store_root(args.root).resolve()
    retention_days = _retention_days(args.days)
    today = _parse_today(args.today)
    cutoff = today - timedelta(days=retention_days)
    targets = find_cleanup_targets(root=root, cutoff=cutoff)

    deleted: list[dict[str, Any]] = []
    if args.apply:
        for target in targets:
            _delete_target(root, target)
            deleted.append(target.to_dict())

    print(
        json.dumps(
            {
                "root": str(root),
                "retention_days": retention_days,
                "today": today.isoformat(),
                "cutoff_before": cutoff.isoformat(),
                "apply": args.apply,
                "target_count": len(targets),
                "targets": [target.to_dict() for target in targets],
                "deleted": deleted,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=None,
        help="Event-store root. Defaults to P6S_EVENT_IMAGE_DIR or logs/p6s_events.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Retention days. Defaults to P6S_EVENT_RETENTION_DAYS or 30.",
    )
    parser.add_argument(
        "--today",
        default="",
        help="Override today's date as YYYY-MM-DD for local validation.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete expired directories. Omit this flag for a dry run.",
    )
    return parser.parse_args()


def find_cleanup_targets(*, root: Path, cutoff: date) -> list[CleanupTarget]:
    targets: list[CleanupTarget] = []
    for subdir in EVENT_SUBDIRS:
        base = root / subdir
        if not base.exists():
            continue
        if not base.is_dir():
            raise RuntimeError(f"event subpath is not a directory: {base}")
        for day_dir in sorted(base.iterdir()):
            if not day_dir.is_dir():
                continue
            day = _parse_day_dir(day_dir.name)
            if day is None or day >= cutoff:
                continue
            files, bytes_count = _tree_stats(day_dir)
            targets.append(
                CleanupTarget(
                    subdir=subdir,
                    day=day_dir.name,
                    path=day_dir,
                    files=files,
                    bytes=bytes_count,
                )
            )
    return targets


def _delete_target(root: Path, target: CleanupTarget) -> None:
    resolved_root = root.resolve()
    resolved_target = target.path.resolve()
    if not _is_relative_to(resolved_target, resolved_root):
        raise RuntimeError(f"refusing to delete outside event root: {target.path}")
    if target.path.parent.name not in EVENT_SUBDIRS:
        raise RuntimeError(f"refusing to delete unexpected path: {target.path}")
    shutil.rmtree(target.path)


def _retention_days(value: int | None) -> int:
    if value is None:
        raw = os.environ.get("P6S_EVENT_RETENTION_DAYS", "30").strip()
        try:
            value = int(raw)
        except ValueError:
            value = 30
    if value < 0:
        raise ValueError("--days must be >= 0")
    return value


def _parse_today(value: str) -> date:
    if not value:
        return event_store.now_local().date()
    return datetime.strptime(value, DAY_FORMAT).date()


def _parse_day_dir(value: str) -> date | None:
    try:
        return datetime.strptime(value, DAY_FORMAT).date()
    except ValueError:
        return None


def _tree_stats(path: Path) -> tuple[int, int]:
    files = 0
    bytes_count = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        files += 1
        bytes_count += item.stat().st_size
    return files, bytes_count


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
