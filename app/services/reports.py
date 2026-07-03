"""Daily attendance report generation and Feishu message building."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.db import attendance_repo
from app.db.config import AttendanceDbSettings
from app.db.session import transaction
from app.services import feishu


@dataclass(frozen=True)
class DailyReportResult:
    report_date: date
    timezone: str
    summary: dict[str, int]
    strangers: list[dict[str, Any]]
    snapshot_saved: bool
    feishu_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.report_date.isoformat(),
            "timezone": self.timezone,
            "summary": self.summary,
            "strangers": self.strangers,
            "snapshot_saved": self.snapshot_saved,
            "feishu": self.feishu_result,
        }


def day_range(report_date: date, timezone_name: str) -> tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    start = datetime.combine(report_date, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def today_for_report(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def generate_daily_report(
    report_date: date,
    *,
    save_snapshot: bool,
    send_feishu: bool,
    settings: AttendanceDbSettings | None = None,
) -> DailyReportResult:
    cfg = settings or AttendanceDbSettings.from_env()
    day_start, day_end = day_range(report_date, cfg.attendance_report_timezone)

    with transaction(cfg) as conn:
        summary = _summary_counts(
            attendance_repo.aggregate_daily_summary(
                conn,
                day_start=day_start,
                day_end=day_end,
            )
        )
        strangers = _normalize_strangers(
            attendance_repo.fetch_daily_strangers(
                conn,
                day_start=day_start,
                day_end=day_end,
            )
        )
        snapshot = _snapshot(report_date, summary, strangers)
        if save_snapshot or send_feishu:
            attendance_repo.upsert_daily_report(conn, snapshot)

    feishu_result = None
    if send_feishu:
        feishu_result = send_daily_report(snapshot, title=cfg.attendance_daily_report_title)

    return DailyReportResult(
        report_date=report_date,
        timezone=cfg.attendance_report_timezone,
        summary=summary,
        strangers=strangers,
        snapshot_saved=save_snapshot or send_feishu,
        feishu_result=feishu_result,
    )


def fetch_daily_report(
    report_date: date,
    *,
    include_events: bool = False,
    settings: AttendanceDbSettings | None = None,
) -> dict[str, Any]:
    cfg = settings or AttendanceDbSettings.from_env()
    with transaction(cfg) as conn:
        snapshot = attendance_repo.fetch_daily_report(conn, report_date=report_date)
        if snapshot:
            summary = _summary_counts(snapshot)
            strangers = _normalize_strangers(_normalize_stranger_items(snapshot.get("stranger_items")))
        else:
            day_start, day_end = day_range(report_date, cfg.attendance_report_timezone)
            summary = _summary_counts(
                attendance_repo.aggregate_daily_summary(
                    conn,
                    day_start=day_start,
                    day_end=day_end,
                )
            )
            strangers = _normalize_strangers(
                attendance_repo.fetch_daily_strangers(
                    conn,
                    day_start=day_start,
                    day_end=day_end,
                )
            )
        events: list[dict[str, Any]] | None = None
        if include_events:
            day_start, day_end = day_range(report_date, cfg.attendance_report_timezone)
            events = _normalize_events(
                attendance_repo.list_attendance_events(
                    conn,
                    day_start=day_start,
                    day_end=day_end,
                    limit=500,
                )
            )

    result: dict[str, Any] = {
        "date": report_date.isoformat(),
        "timezone": cfg.attendance_report_timezone,
        "summary": summary,
        "strangers": strangers,
    }
    if events is not None:
        result["events"] = events
    return result


def list_events(
    report_date: date,
    *,
    person_type: str | None,
    limit: int,
    offset: int,
    settings: AttendanceDbSettings | None = None,
) -> dict[str, Any]:
    cfg = settings or AttendanceDbSettings.from_env()
    day_start, day_end = day_range(report_date, cfg.attendance_report_timezone)
    with transaction(cfg) as conn:
        events = attendance_repo.list_attendance_events(
            conn,
            day_start=day_start,
            day_end=day_end,
            person_type=person_type,
            limit=limit,
            offset=offset,
        )
    return {
        "date": report_date.isoformat(),
        "timezone": cfg.attendance_report_timezone,
        "items": _normalize_events(events),
        "limit": max(1, min(limit, 500)),
        "offset": max(0, offset),
    }


def send_daily_report(snapshot: dict[str, Any], *, title: str) -> dict[str, Any]:
    return feishu.send_post(title, build_daily_report_lines(snapshot))


def build_daily_report_lines(snapshot: dict[str, Any]) -> list[list[dict[str, str]]]:
    report_date = snapshot.get("report_date")
    if isinstance(report_date, date):
        report_date_text = report_date.isoformat()
    else:
        report_date_text = str(report_date)

    lines = [
        _text_line("报告日期", report_date_text),
        _text_line("会员入场次数", _count_text(snapshot, "member_entries")),
        _text_line("教练入场次数", _count_text(snapshot, "coach_entries")),
        _text_line("员工入场次数", _count_text(snapshot, "staff_entries")),
        _text_line("陌生人入场次数", _count_text(snapshot, "stranger_entries")),
        _text_line("未知身份入场次数", _count_text(snapshot, "unknown_known_entries")),
        _text_line("实际发送飞书数量", _count_text(snapshot, "notification_sent_count")),
        _text_line("去重抑制数量", _count_text(snapshot, "notification_suppressed_count")),
    ]
    strangers = _normalize_stranger_items(snapshot.get("stranger_items"))
    if strangers:
        lines.append([{"tag": "text", "text": "陌生人照片："}])
        for item in strangers:
            label = _stranger_link_label(item)
            href = str(item.get("image_url") or "")
            if href:
                lines.append([{"tag": "a", "text": label, "href": href}])
            else:
                lines.append([{"tag": "text", "text": f"{label} 无可用链接"}])
    return lines


def _snapshot(report_date: date, summary: dict[str, int], strangers: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "report_date": report_date,
        **summary,
        "stranger_items": strangers,
    }


def _summary_counts(row: dict[str, Any]) -> dict[str, int]:
    return {
        "member_entries": int(row.get("member_entries") or 0),
        "coach_entries": int(row.get("coach_entries") or 0),
        "staff_entries": int(row.get("staff_entries") or 0),
        "stranger_entries": int(row.get("stranger_entries") or 0),
        "unknown_known_entries": int(row.get("unknown_known_entries") or 0),
        "notification_sent_count": int(row.get("notification_sent_count") or 0),
        "notification_suppressed_count": int(row.get("notification_suppressed_count") or 0),
    }


def _normalize_strangers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_json_safe_dict(row) for row in rows]


def _normalize_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_json_safe_dict(row) for row in rows]


def _normalize_stranger_items(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [item for item in (_json_safe_dict(row) for row in value) if item]


def _json_safe_dict(row: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(row).items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, date):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def _text_line(label: str, value: str) -> list[dict[str, str]]:
    return [{"tag": "text", "text": f"{label}：{value}"}]


def _count_text(snapshot: dict[str, Any], key: str) -> str:
    return str(int(snapshot.get(key) or 0))


def _stranger_link_label(item: dict[str, Any]) -> str:
    event_time = str(item.get("event_time") or "")
    if "T" in event_time:
        time_part = event_time.split("T", 1)[1][:8]
    elif " " in event_time:
        time_part = event_time.split(" ", 1)[1][:8]
    else:
        time_part = event_time[:8] or "未知时间"
    return f"{time_part} 查看图片"
