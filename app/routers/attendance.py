"""Attendance report and event management APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.db.config import AttendanceDbSettings
from app.routers.auth import require_admin
from app.services import reports

router = APIRouter()

PERSON_TYPES = {"member", "coach", "staff", "stranger", "unknown_known"}


class SnapshotRequest(BaseModel):
    send_feishu: bool = False


@router.get("/attendance/reports/daily")
def get_daily_report(
    report_date: date | None = Query(default=None, alias="date"),
    include_events: bool = False,
    _: dict[str, Any] = Depends(require_admin),
):
    day = report_date or _today_from_settings()
    try:
        return reports.fetch_daily_report(day, include_events=include_events)
    except Exception as exc:
        raise _db_unavailable(exc)


@router.post("/attendance/reports/daily/{report_date}/snapshot")
def create_daily_report_snapshot(
    report_date: date,
    body: SnapshotRequest,
    _: dict[str, Any] = Depends(require_admin),
):
    try:
        return reports.generate_daily_report(
            report_date,
            save_snapshot=True,
            send_feishu=body.send_feishu,
        ).to_dict()
    except Exception as exc:
        raise _db_unavailable(exc)


@router.get("/attendance/events")
def list_attendance_events(
    report_date: date | None = Query(default=None, alias="date"),
    person_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _: dict[str, Any] = Depends(require_admin),
):
    if person_type and person_type not in PERSON_TYPES:
        raise HTTPException(status_code=400, detail="unsupported person_type")
    day = report_date or _today_from_settings()
    try:
        return reports.list_events(
            day,
            person_type=person_type,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise _db_unavailable(exc)


def _db_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"attendance database unavailable: {type(exc).__name__}")


def _today_from_settings() -> date:
    return reports.today_for_report(AttendanceDbSettings.from_env().attendance_report_timezone)
