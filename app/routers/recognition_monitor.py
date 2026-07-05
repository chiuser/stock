"""Recognition monitor APIs."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.db import recognition_repo
from app.routers.auth import require_admin
from app.services import recognition_monitor

router = APIRouter()


@router.get("/recognition-monitor/summary")
def get_recognition_summary(
    event_date: date = Query(alias="date"),
    _: dict[str, Any] = Depends(require_admin),
):
    try:
        with recognition_repo.transaction() as conn:
            summary = recognition_repo.fetch_summary(conn, event_date=event_date)
        return recognition_monitor.build_summary_response(summary)
    except Exception as exc:
        raise _db_unavailable(exc)


@router.get("/recognition-monitor/events")
def list_recognition_events(
    event_date: date = Query(alias="date"),
    classification: str | None = None,
    camera_result: str | None = None,
    recheck_status: str | None = None,
    reason: str | None = None,
    person: str | None = None,
    accepted: bool | None = None,
    page: int = 1,
    page_size: int | None = None,
    _: dict[str, Any] = Depends(require_admin),
):
    default_size, max_size = recognition_monitor.page_size_from_env()
    safe_page = max(1, page)
    safe_page_size = max(1, min(page_size or default_size, max_size))
    try:
        with recognition_repo.transaction() as conn:
            result = recognition_repo.list_events(
                conn,
                event_date=event_date,
                classification=_clean_filter(classification),
                camera_result=_clean_filter(camera_result),
                recheck_status=_clean_filter(recheck_status),
                reason=_clean_filter(reason),
                person=_clean_filter(person),
                accepted=accepted,
                limit=safe_page_size,
                offset=(safe_page - 1) * safe_page_size,
            )
        return recognition_monitor.build_events_response(
            event_date=event_date,
            page=safe_page,
            page_size=safe_page_size,
            total=result["total"],
            rows=result["items"],
        )
    except Exception as exc:
        raise _db_unavailable(exc)


@router.get("/recognition-monitor/events/{event_key}")
def get_recognition_event(
    event_key: str,
    _: dict[str, Any] = Depends(require_admin),
):
    try:
        with recognition_repo.transaction() as conn:
            row = recognition_repo.fetch_event(conn, event_key=event_key)
    except Exception as exc:
        raise _db_unavailable(exc)
    if row is None:
        raise HTTPException(status_code=404, detail="recognition event not found")
    return recognition_monitor.row_to_event(row, include_detail=True)


@router.get("/recognition-monitor/quality")
def get_recognition_quality(
    date_from: date,
    date_to: date,
    _: dict[str, Any] = Depends(require_admin),
):
    if date_to < date_from:
        raise HTTPException(status_code=400, detail="date_to must be greater than or equal to date_from")
    if date_to - date_from > timedelta(days=13):
        raise HTTPException(status_code=400, detail="date range must not exceed 14 days")
    try:
        with recognition_repo.transaction() as conn:
            overview = recognition_repo.fetch_quality_overview(conn, date_from=date_from, date_to=date_to)
        return recognition_monitor.build_quality_response(overview)
    except HTTPException:
        raise
    except Exception as exc:
        raise _db_unavailable(exc)


@router.get("/recognition-monitor/images")
def get_recognition_image(
    relative_path: str,
    _: dict[str, Any] = Depends(require_admin),
):
    try:
        image_path, content_type = recognition_monitor.resolve_image_path(relative_path)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid image path")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(image_path, media_type=content_type)


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _db_unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail=f"recognition monitor database unavailable: {type(exc).__name__}")
