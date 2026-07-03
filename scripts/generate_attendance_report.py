"""Generate, save, and optionally send a daily attendance report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.config import AttendanceDbSettings, load_env_file
from app.services import reports


def main() -> int:
    args = parse_args()
    if args.env_file:
        load_env_file(args.env_file)
    if args.send_feishu and not args.save_snapshot:
        raise SystemExit("--send-feishu requires --save-snapshot so the sent content matches the saved snapshot")

    settings = AttendanceDbSettings.from_env()
    report_date = args.date or reports.today_for_report(settings.attendance_report_timezone)
    result = reports.generate_daily_report(
        report_date,
        save_snapshot=args.save_snapshot,
        send_feishu=args.send_feishu,
        settings=settings,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=_json_default))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env.local")
    parser.add_argument("--date", type=_parse_date, default=None, help="Report date as YYYY-MM-DD.")
    parser.add_argument("--save-snapshot", action="store_true", help="Upsert daily_attendance_reports.")
    parser.add_argument("--send-feishu", action="store_true", help="Send the daily report to Feishu.")
    return parser.parse_args()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _json_default(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
