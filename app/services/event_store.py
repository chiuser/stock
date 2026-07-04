"""Filesystem-backed storage for P6S event processing artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_SAFE_PART_RE = re.compile(r"[^0-9A-Za-z_-]+")


class EventStoreError(RuntimeError):
    """Base error for event-store failures."""


class UnsupportedImageTypeError(EventStoreError):
    """Raised when an image is empty or not a supported JPEG/PNG file."""


@dataclass(frozen=True)
class RequestMeta:
    client_host: str = ""
    content_type: str = ""
    user_agent: str = ""
    method: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "client_host": self.client_host,
            "content_type": self.content_type,
            "user_agent": self.user_agent,
            "method": self.method,
            "path": self.path,
        }


@dataclass(frozen=True)
class EventStorePaths:
    root: Path
    day: str
    raw_dir: Path
    records_dir: Path
    faces_dir: Path
    strangers_dir: Path
    links_dir: Path


@dataclass(frozen=True)
class EventIdentity:
    dedupe_key: str
    operator: str
    serial_number: str
    event_id: str
    picture_md5: str
    event_time: str
    event_time_compact: str
    received_at: datetime
    event_day: str


@dataclass(frozen=True)
class StoredFile:
    path: Path
    relative_path: str
    byte_size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "relative_path": self.relative_path,
            "bytes": self.byte_size,
        }


@dataclass(frozen=True)
class StoredImage:
    path: Path
    relative_path: str
    content_type: str
    byte_size: int
    md5: str
    md5_ok: bool | None
    source: str
    image_kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "status": "saved",
            "source": self.source,
            "storage_path": str(self.path),
            "relative_path": self.relative_path,
            "content_type": self.content_type,
            "bytes": self.byte_size,
            "md5": self.md5,
            "md5_ok": self.md5_ok,
        }
        if self.image_kind:
            data["kind"] = self.image_kind
        return data


def now_local() -> datetime:
    return datetime.now(_LOCAL_TZ)


def event_store_root(root: Path | str | None = None) -> Path:
    if root is not None:
        return Path(root).expanduser()
    configured = os.environ.get("P6S_EVENT_IMAGE_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _PROJECT_ROOT / "logs" / "p6s_events"


def ensure_event_store_dirs(
    *,
    day: str | None = None,
    root: Path | str | None = None,
) -> EventStorePaths:
    store_root = event_store_root(root)
    event_day = day or now_local().strftime("%Y-%m-%d")
    paths = EventStorePaths(
        root=store_root,
        day=event_day,
        raw_dir=store_root / "raw" / event_day,
        records_dir=store_root / "records" / event_day,
        faces_dir=store_root / "faces" / event_day,
        strangers_dir=store_root / "strangers" / event_day,
        links_dir=store_root / "links" / event_day,
    )
    for directory in (
        paths.raw_dir,
        paths.records_dir,
        paths.faces_dir,
        paths.strangers_dir,
        paths.links_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return paths


def build_event_identity(
    payload: dict[str, Any],
    *,
    received_at: datetime | None = None,
) -> EventIdentity:
    received = received_at or now_local()
    if received.tzinfo is None:
        received = received.replace(tzinfo=_LOCAL_TZ)
    received = received.astimezone(_LOCAL_TZ)

    info = payload.get("info") or {}
    operator = str(payload.get("operator") or "event")
    serial_number = _extract_serial_number(payload)
    event_id = _first_str(
        info.get("eventId"),
        info.get("EventId"),
        info.get("eventID"),
        info.get("id"),
    )
    picture_md5 = _extract_picture_md5(info)
    event_time = _first_str(
        info.get("time"),
        info.get("Time"),
        info.get("eventTime"),
        info.get("EventTime"),
    )
    event_time_compact = _compact_time(event_time, received)
    event_day = _event_day(event_time, received)
    dedupe_key = build_dedupe_key(
        serial_number=serial_number,
        operator=operator,
        event_id=event_id,
        picture_md5=picture_md5,
        received_at=received,
    )

    return EventIdentity(
        dedupe_key=dedupe_key,
        operator=operator,
        serial_number=serial_number,
        event_id=event_id,
        picture_md5=picture_md5,
        event_time=event_time,
        event_time_compact=event_time_compact,
        received_at=received,
        event_day=event_day,
    )


def build_dedupe_key(
    *,
    serial_number: str,
    operator: str,
    event_id: str,
    picture_md5: str,
    received_at: datetime,
) -> str:
    parts = [serial_number, operator, event_id, picture_md5]
    if not event_id or not picture_md5:
        parts.append(received_at.isoformat())
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def persist_raw_event(
    payload: dict[str, Any],
    *,
    request_meta: RequestMeta | None = None,
    identity: EventIdentity | None = None,
    root: Path | str | None = None,
) -> StoredFile:
    event_identity = identity or build_event_identity(payload)
    paths = ensure_event_store_dirs(day=event_identity.event_day, root=root)
    path = paths.raw_dir / f"{event_identity.dedupe_key}.json"
    content = {
        "version": 1,
        "dedupe_key": event_identity.dedupe_key,
        "received_at": event_identity.received_at.isoformat(),
        "request": (request_meta or RequestMeta()).to_dict(),
        "payload": payload,
    }
    _atomic_write_json(path, content)
    return _stored_file(path, root=paths.root)


def processing_record_path(
    identity: EventIdentity,
    *,
    root: Path | str | None = None,
) -> Path:
    paths = ensure_event_store_dirs(day=identity.event_day, root=root)
    return paths.records_dir / f"{identity.dedupe_key}.json"


def processing_record_exists(
    identity: EventIdentity,
    *,
    root: Path | str | None = None,
) -> bool:
    return processing_record_path(identity, root=root).exists()


def write_processing_record(
    identity: EventIdentity,
    record: dict[str, Any],
    *,
    root: Path | str | None = None,
) -> StoredFile:
    path = processing_record_path(identity, root=root)
    content = {
        "version": 1,
        "dedupe_key": identity.dedupe_key,
        "operator": identity.operator,
        "camera_serial_number": identity.serial_number,
        "event_id": identity.event_id,
        "event_time": identity.event_time,
        "received_at": identity.received_at.isoformat(),
        **record,
    }
    _atomic_write_json(path, content)
    return _stored_file(path, root=event_store_root(root))


def save_stranger_image(
    identity: EventIdentity,
    image_bytes: bytes,
    *,
    source: str,
    expected_md5: str | None = None,
    root: Path | str | None = None,
    max_bytes: int | None = None,
    image_kind: str | None = None,
) -> StoredImage:
    return save_face_image(
        identity,
        image_bytes,
        source=source,
        expected_md5=expected_md5,
        root=root,
        max_bytes=max_bytes,
        category="strangers",
        image_kind=image_kind,
    )


def save_face_image(
    identity: EventIdentity,
    image_bytes: bytes,
    *,
    source: str,
    expected_md5: str | None = None,
    root: Path | str | None = None,
    max_bytes: int | None = None,
    category: str = "faces",
    image_kind: str | None = None,
) -> StoredImage:
    byte_limit = max_bytes if max_bytes is not None else _max_image_bytes()
    if not image_bytes:
        raise UnsupportedImageTypeError("image is empty")
    if len(image_bytes) > byte_limit:
        raise UnsupportedImageTypeError("image is larger than P6S_EVENT_MAX_IMAGE_BYTES")

    content_type, extension = detect_image_type(image_bytes)
    actual_md5 = hashlib.md5(image_bytes).hexdigest()
    expected = (expected_md5 or "").strip().lower()
    md5_ok = actual_md5 == expected if expected else None
    paths = ensure_event_store_dirs(day=identity.event_day, root=root)
    target_dir = _image_target_dir(paths, category)
    filename = _face_image_filename(
        identity=identity,
        image_md5=expected or actual_md5,
        fallback_hash=hashlib.sha256(image_bytes).hexdigest(),
        extension=extension,
        image_kind=image_kind,
    )
    path = target_dir / filename
    _atomic_write_bytes(path, image_bytes)
    return StoredImage(
        path=path,
        relative_path=relative_to_root(path, root=paths.root),
        content_type=content_type,
        byte_size=len(image_bytes),
        md5=actual_md5,
        md5_ok=md5_ok,
        source=source,
        image_kind=image_kind,
    )


def _image_target_dir(paths: EventStorePaths, category: str) -> Path:
    if category == "faces":
        return paths.faces_dir
    if category == "strangers":
        return paths.strangers_dir
    raise EventStoreError(f"unsupported face image category: {category}")


def detect_image_type(image_bytes: bytes) -> tuple[str, str]:
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    raise UnsupportedImageTypeError("unsupported image type")


def relative_to_root(path: Path, *, root: Path | str | None = None) -> str:
    store_root = event_store_root(root).resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(store_root).as_posix()
    except ValueError as exc:
        raise EventStoreError(f"path is outside event store root: {path}") from exc


def safe_filename_part(value: Any, *, default: str = "unknown", max_length: int = 64) -> str:
    text = str(value or "").strip()
    cleaned = _SAFE_PART_RE.sub("_", text).strip("._-")
    if not cleaned:
        cleaned = default
    return cleaned[:max_length]


def _stored_file(path: Path, *, root: Path) -> StoredFile:
    return StoredFile(
        path=path,
        relative_path=relative_to_root(path, root=root),
        byte_size=path.stat().st_size,
    )


def _face_image_filename(
    *,
    identity: EventIdentity,
    image_md5: str,
    fallback_hash: str,
    extension: str,
    image_kind: str | None = None,
) -> str:
    serial = safe_filename_part(identity.serial_number, default="device")
    event_id = safe_filename_part(identity.event_id, default="event")
    kind = safe_filename_part(image_kind, default="", max_length=32) if image_kind else ""
    md5_part = re.sub(r"[^0-9A-Fa-f]", "", image_md5)[:8]
    if not md5_part:
        md5_part = fallback_hash[:8]
    if kind:
        return f"{identity.event_time_compact}_{serial}_{event_id}_{kind}_{md5_part}.{extension}"
    return f"{identity.event_time_compact}_{serial}_{event_id}_{md5_part}.{extension}"


def _extract_serial_number(payload: dict[str, Any]) -> str:
    device_info = (
        payload.get("deviceInfo")
        or payload.get("deviceinfo")
        or payload.get("device_info")
        or {}
    )
    return _first_str(
        device_info.get("serialNumber"),
        device_info.get("SerialNumber"),
        device_info.get("deviceSerialNumber"),
        device_info.get("SN"),
        device_info.get("sn"),
        default="unknown",
    )


def _extract_picture_md5(info: dict[str, Any]) -> str:
    for image_key in ("CaptureImage", "BackgroundImage", "recognizeImage"):
        image_info = info.get(image_key) or {}
        value = _first_str(
            image_info.get("pictureMd5"),
            image_info.get("PictureMd5"),
            image_info.get("pictureMD5"),
            image_info.get("md5"),
        )
        if value:
            return value
    return ""


def _compact_time(value: str, fallback: datetime) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 14:
        return digits[:14]
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(_LOCAL_TZ).strftime("%Y%m%d%H%M%S")
        except ValueError:
            pass
    return fallback.astimezone(_LOCAL_TZ).strftime("%Y%m%d%H%M%S")


def _event_day(value: str, fallback: datetime) -> str:
    digits = re.sub(r"\D", "", value or "")
    if len(digits) >= 8:
        try:
            parsed = datetime.strptime(digits[:8], "%Y%m%d")
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            pass
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(_LOCAL_TZ).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return fallback.astimezone(_LOCAL_TZ).strftime("%Y-%m-%d")


def _first_str(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _max_image_bytes() -> int:
    value = os.environ.get("P6S_EVENT_MAX_IMAGE_BYTES", "5242880").strip()
    try:
        return max(1, int(value))
    except ValueError:
        return 5_242_880


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    _atomic_write_bytes(path, text.encode("utf-8"))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        tmp_path.write_bytes(data)
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")
