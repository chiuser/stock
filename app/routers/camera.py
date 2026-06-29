"""P6S camera management and event callback APIs."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.routers.auth import require_admin
from app.services import feishu
from app.services.p6s_camera import (
    P6SCameraClient,
    P6SConfig,
    generate_owner,
)

router = APIRouter()

_PROJECT_ROOT = Path(__file__).parent.parent.parent


class OwnerRequest(BaseModel):
    owner: str | None = None


class FaceGroupRequest(BaseModel):
    group_id: str | None = None
    group_name: str | None = None
    threshold: int | None = None
    owner: str | None = None


class UploadFaceRequest(BaseModel):
    member_id: str
    name: str | None = None
    group_id: str | None = None
    owner: str | None = None


class BatchUploadRequest(BaseModel):
    limit: int | None = None
    member_ids: list[str] | None = None
    group_id: str | None = None
    owner: str | None = None


def _face_dir() -> Path:
    return Path(os.environ.get("P6S_FACE_DIR", _PROJECT_ROOT / "styd_member_faces"))


def _event_dir() -> Path:
    return Path(os.environ.get("P6S_EVENT_IMAGE_DIR", _PROJECT_ROOT / "logs" / "p6s_events"))


def _event_secret() -> str:
    return os.environ.get("P6S_EVENT_SECRET", "").strip()


def _public_base_url() -> str:
    return os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")


def _list_face_files() -> list[dict[str, Any]]:
    face_dir = _face_dir()
    if not face_dir.exists():
        return []
    rows = []
    for path in sorted(face_dir.glob("*.jpg")):
        rows.append(
            {
                "member_id": path.stem,
                "file": path.name,
                "bytes": path.stat().st_size,
            }
        )
    return rows


def _find_face_image(member_id: str) -> Path:
    safe_member_id = re.sub(r"[^0-9A-Za-z_-]", "", member_id)
    return _face_dir() / f"{safe_member_id}.jpg"


@router.get("/camera/status")
def camera_status(_: dict = Depends(require_admin)):
    face_files = _list_face_files()
    event_files = list(_event_dir().glob("*.json")) if _event_dir().exists() else []
    return {
        "camera": P6SConfig.from_env().safe_summary(),
        "faces": {
            "dir": str(_face_dir()),
            "count": len(face_files),
            "sample": face_files[:10],
        },
        "events": {
            "dir": str(_event_dir()),
            "count": len(event_files),
            "has_secret": bool(_event_secret()),
            "public_base_url": _public_base_url(),
        },
        "feishu": feishu.FeishuConfig.from_env().safe_summary(),
    }


@router.post("/camera/test-connection")
def test_camera_connection(_: dict = Depends(require_admin)):
    return P6SCameraClient().get_owner()


@router.post("/camera/owner")
def set_camera_owner(body: OwnerRequest, _: dict = Depends(require_admin)):
    owner = (body.owner or "").strip() or generate_owner()
    result = P6SCameraClient().set_owner(owner)
    return {"owner": owner, "result": result}


@router.post("/camera/face-group")
def create_face_group(body: FaceGroupRequest, _: dict = Depends(require_admin)):
    result = P6SCameraClient().create_group(
        group_id=body.group_id,
        group_name=body.group_name,
        threshold=body.threshold,
        owner=body.owner,
    )
    return result


@router.get("/camera/faces")
def list_faces(_: dict = Depends(require_admin)):
    rows = _list_face_files()
    return {"dir": str(_face_dir()), "count": len(rows), "items": rows}


@router.post("/camera/faces/upload")
def upload_face(body: UploadFaceRequest, _: dict = Depends(require_admin)):
    image_path = _find_face_image(body.member_id)
    return P6SCameraClient().upload_person_image(
        image_path=image_path,
        unique_id=body.member_id,
        name=body.name,
        face_group_id=body.group_id,
        owner=body.owner,
    )


@router.post("/camera/faces/upload-batch")
def upload_faces_batch(body: BatchUploadRequest, _: dict = Depends(require_admin)):
    items = _list_face_files()
    if body.member_ids:
        wanted = set(body.member_ids)
        items = [item for item in items if item["member_id"] in wanted]
    if body.limit is not None:
        items = items[: max(0, body.limit)]

    client = P6SCameraClient()
    results = []
    for item in items:
        results.append(
            client.upload_person_image(
                image_path=_find_face_image(item["member_id"]),
                unique_id=item["member_id"],
                face_group_id=body.group_id,
                owner=body.owner,
            )
        )

    ok_count = sum(1 for result in results if result.get("ok"))
    return {
        "total": len(results),
        "ok": ok_count,
        "failed": len(results) - ok_count,
        "results": results,
    }


@router.post("/camera/feishu/test")
def test_feishu(_: dict = Depends(require_admin)):
    return feishu.send_text("摄像头告警通知测试：如果你看到这条消息，飞书机器人已连通。")


@router.post("/p6s/events")
async def p6s_events(
    request: Request,
    background_tasks: BackgroundTasks,
):
    return await _handle_p6s_event(request, background_tasks)


@router.post("/p6s/events/{path_secret}")
async def p6s_events_with_secret(
    path_secret: str,
    request: Request,
    background_tasks: BackgroundTasks,
):
    return await _handle_p6s_event(request, background_tasks, path_secret=path_secret)


@router.get("/p6s/event-images/{filename}")
def get_event_image(filename: str):
    safe_name = re.sub(r"[^0-9A-Za-z_.-]", "", filename)
    path = _event_dir() / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path)


async def _handle_p6s_event(
    request: Request,
    background_tasks: BackgroundTasks,
    path_secret: str | None = None,
) -> dict[str, Any]:
    _validate_event_secret(request, path_secret)
    payload = await request.json()
    operator = payload.get("operator", "")

    _persist_event_payload(payload)

    if operator == "heartbeat":
        return _heartbeat_ack(payload)

    if operator == "FaceReco":
        image_path = _handle_face_reco(payload, background_tasks)
        return _face_reco_ack(payload, image_path)

    return {
        "operator": f"{operator}-Ack" if operator else "Ack",
        "result": {"errorNo": 0, "description": "ok"},
    }


def _validate_event_secret(request: Request, path_secret: str | None) -> None:
    expected = _event_secret()
    if not expected:
        return

    provided = (
        path_secret
        or request.query_params.get("secret")
        or request.headers.get("X-P6S-Event-Secret")
        or ""
    )
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid P6S event secret",
        )


def _heartbeat_ack(payload: dict[str, Any]) -> dict[str, Any]:
    info = payload.get("info") or {}
    return {
        "operator": "heartbeat-Ack",
        "info": {
            "eventId": info.get("eventId", 1),
            "time": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S+08"),
            "eventSendMode": os.environ.get("P6S_EVENT_SEND_MODE", "realTime"),
            "strategy": _event_strategy(),
        },
        "result": {"errorNo": 0, "description": "ok"},
    }


def _event_strategy() -> dict[str, Any]:
    # P6S requires the heartbeat response to explicitly enable event reporting.
    return {
        "passengerStaticsInterval": int(os.environ.get("P6S_PASSENGER_INTERVAL", "2")),
        "heartBeatInterval": int(os.environ.get("P6S_HEARTBEAT_INTERVAL", "30")),
        "isEnableElectronicDefence": False,
        "isCrossBorderDetectEnable": False,
        "isOffDutyDetectEnable": False,
        "isPassengerFlowStaticsEnable": False,
        "isCryScreamDetectEnable": False,
        "isPetDetectEnable": False,
        "isFallDetectEnable": False,
        "isSnapshotEnable": True,
        "isPersonInfoEnable": True,
        "isPersonDetectEnable": False,
        "isCarLicenseSnapshotEnable": False,
        "isCarDetectEnable": False,
        "isTimedSnapshotEnable": False,
        "isGroundLockStatusChangedEnable": False,
        "isStartupReportEnable": True,
        "isAbnormalEventEnable": False,
        "isNonWhitelistCarEnable": False,
        "isMotionDetectEnable": False,
        "isTrafficStatisticsEnable": False,
        "isTrafficStatisticsCarShapeEnable": False,
        "isKey2CallEnable": False,
        "isLicensePlateSurveillanceEnable": False,
        "isFireDetectEventEnable": False,
        "isVideoCoverEventEnable": False,
        "isElectricBikeEventEnable": False,
        "isGasContainerEventEnable": False,
        "isElectronicDefenceV2EventEnable": False,
        "isPeopleNumberStatisticsEventEnable": False,
        "isPeopleNumberOverLimitEventEnable": False,
    }


def _handle_face_reco(
    payload: dict[str, Any],
    background_tasks: BackgroundTasks,
) -> Path | None:
    info = payload.get("info") or {}
    person_info = info.get("personInfo")
    is_stranger = not person_info
    if not is_stranger:
        return None

    image_path = _save_capture_image(payload)
    device_info = payload.get("deviceInfo") or {}
    background_tasks.add_task(
        feishu.notify_unknown_face,
        image_path=image_path,
        device_sn=device_info.get("serialNumber") or device_info.get("SN") or "",
        event_time=str(info.get("time") or ""),
        event_id=info.get("eventId"),
    )
    return image_path


def _face_reco_ack(payload: dict[str, Any], image_path: Path | None) -> dict[str, Any]:
    info = payload.get("info") or {}
    person_info = info.get("personInfo") or {}
    capture = info.get("CaptureImage") or {}
    return {
        "operator": "FaceReco-Ack",
        "info": {
            "personId": person_info.get("personId", 0),
            "uniqueId": person_info.get("uniqueId", ""),
            "pictureMd5": capture.get("pictureMd5", ""),
            "storedImage": str(image_path) if image_path else "",
        },
        "result": {"errorNo": 0, "description": "ok"},
    }


def _save_capture_image(payload: dict[str, Any]) -> Path | None:
    info = payload.get("info") or {}
    capture = info.get("CaptureImage") or {}
    picture = capture.get("picture", "")
    if not picture:
        return None

    if "," in picture:
        _, picture = picture.split(",", 1)

    try:
        raw = base64.b64decode(picture)
    except Exception:
        return None
    event_dir = _event_dir()
    event_dir.mkdir(parents=True, exist_ok=True)

    device_info = payload.get("deviceInfo") or {}
    device_sn = re.sub(
        r"[^0-9A-Za-z_-]",
        "",
        str(device_info.get("serialNumber") or device_info.get("SN") or "device"),
    )
    event_id = re.sub(r"[^0-9A-Za-z_-]", "", str(info.get("eventId") or "event"))
    md5_part = re.sub(r"[^0-9A-Fa-f]", "", str(capture.get("pictureMd5") or ""))[:8]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{ts}_{device_sn}_{event_id}_{md5_part or 'image'}.jpg"
    path = event_dir / filename
    path.write_bytes(raw)
    return path


def _persist_event_payload(payload: dict[str, Any]) -> None:
    event_dir = _event_dir()
    event_dir.mkdir(parents=True, exist_ok=True)
    operator = re.sub(r"[^0-9A-Za-z_-]", "", str(payload.get("operator") or "event"))
    event_id = re.sub(
        r"[^0-9A-Za-z_-]",
        "",
        str((payload.get("info") or {}).get("eventId") or "unknown"),
    )
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    path = event_dir / f"{ts}_{operator}_{event_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
