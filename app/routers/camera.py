"""P6S camera management and event callback APIs."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.routers.auth import require_admin
from app.services import event_store, feishu, image_links
from app.services import p6s_events as p6s_event_service
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
    event_files = list(_event_dir().glob("raw/*/*.json")) if _event_dir().exists() else []
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
):
    return await _handle_p6s_event(request)


@router.post("/p6s/events/{path_secret}")
async def p6s_events_with_secret(
    path_secret: str,
    request: Request,
):
    return await _handle_p6s_event(request, path_secret=path_secret)


@router.get("/p6s/event-images/view/{token}")
def get_event_image_by_token(token: str):
    try:
        resolved = image_links.resolve_image_link(token)
    except (image_links.InvalidImageTokenError, image_links.ImageLinkNotFoundError):
        raise HTTPException(status_code=404, detail="image link not found")
    except image_links.ImageLinkExpiredError:
        raise HTTPException(status_code=410, detail="image link expired")
    except image_links.ImageLinkPathError:
        raise HTTPException(status_code=403, detail="image link target is invalid")
    except image_links.ImageLinkFileNotFoundError:
        raise HTTPException(status_code=404, detail="image file not found")
    return FileResponse(resolved.image_path, media_type=resolved.content_type)


@router.get("/p6s/event-images/{filename}")
def get_event_image(filename: str):
    safe_name = re.sub(r"[^0-9A-Za-z_.-]", "", filename)
    path = _event_dir() / safe_name
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path)


async def _handle_p6s_event(
    request: Request,
    path_secret: str | None = None,
) -> dict[str, Any]:
    _validate_event_secret(request, path_secret)
    body = await request.body()
    if len(body) > _max_event_body_bytes():
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="P6S event body is too large",
        )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid P6S event JSON")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="P6S event JSON must be an object")

    result = await p6s_event_service.handle_event(
        payload,
        request_meta=_event_request_meta(request),
    )
    return result.ack


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


def _event_request_meta(request: Request) -> event_store.RequestMeta:
    return event_store.RequestMeta(
        client_host=request.client.host if request.client else "",
        content_type=request.headers.get("content-type", ""),
        user_agent=request.headers.get("user-agent", ""),
        method=request.method,
        path=request.url.path,
    )


def _max_event_body_bytes() -> int:
    value = os.environ.get("P6S_EVENT_MAX_BODY_BYTES", "5242880").strip()
    try:
        return max(1, int(value))
    except ValueError:
        return 5_242_880
