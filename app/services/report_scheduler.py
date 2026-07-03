"""Lightweight in-process scheduler for the daily attendance report."""

from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.db.config import AttendanceDbSettings
from app.services import reports

_TASK: asyncio.Task[None] | None = None
_STOP_EVENT: asyncio.Event | None = None


async def start_daily_report_scheduler() -> None:
    global _TASK, _STOP_EVENT
    settings = AttendanceDbSettings.from_env()
    if not (settings.attendance_db_enabled and settings.attendance_daily_report_enabled):
        return
    if _TASK is not None and not _TASK.done():
        return
    _STOP_EVENT = asyncio.Event()
    _TASK = asyncio.create_task(_daily_report_loop(_STOP_EVENT), name="attendance-daily-report")


async def stop_daily_report_scheduler() -> None:
    global _TASK, _STOP_EVENT
    if _STOP_EVENT is not None:
        _STOP_EVENT.set()
    if _TASK is not None:
        try:
            await asyncio.wait_for(_TASK, timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _TASK.cancel()
    _TASK = None
    _STOP_EVENT = None


async def _daily_report_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        settings = AttendanceDbSettings.from_env()
        next_run = compute_next_run_time(
            time_text=settings.attendance_daily_report_time,
            timezone_name=settings.attendance_report_timezone,
        )
        await _wait_until(next_run, stop_event)
        if stop_event.is_set():
            break
        await asyncio.to_thread(
            reports.generate_daily_report,
            next_run.date(),
            save_snapshot=True,
            send_feishu=True,
        )


def compute_next_run_time(*, time_text: str, timezone_name: str, now: datetime | None = None) -> datetime:
    tz = ZoneInfo(timezone_name)
    current = now.astimezone(tz) if now else datetime.now(tz)
    target_time = _parse_time(time_text)
    candidate = datetime.combine(current.date(), target_time, tzinfo=tz)
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


async def _wait_until(target: datetime, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        seconds = (target - datetime.now(target.tzinfo)).total_seconds()
        if seconds <= 0:
            return
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=min(seconds, 60))
        except asyncio.TimeoutError:
            continue


def _parse_time(value: str) -> time:
    try:
        hour_text, minute_text = value.strip().split(":", 1)
        return time(hour=max(0, min(23, int(hour_text))), minute=max(0, min(59, int(minute_text))))
    except (AttributeError, ValueError):
        return time(hour=22, minute=0)
