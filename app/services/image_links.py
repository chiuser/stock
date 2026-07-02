"""Token-based image links for stored P6S event images."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.services import event_store

_LOCAL_TZ = ZoneInfo("Asia/Shanghai")
_TOKEN_RE = re.compile(r"^[0-9A-Za-z_-]{20,256}$")


class ImageLinkError(RuntimeError):
    """Base error for image-link failures."""


class InvalidImageTokenError(ImageLinkError):
    """Raised when a token contains unexpected characters."""


class ImageLinkNotFoundError(ImageLinkError):
    """Raised when a token hash has no link record."""


class ImageLinkExpiredError(ImageLinkError):
    """Raised when a link record has expired."""


class ImageLinkTargetError(ImageLinkError):
    """Raised when a link record points to an invalid image target."""


class ImageLinkPathError(ImageLinkTargetError):
    """Raised when a link record points outside the event image root."""


class ImageLinkFileNotFoundError(ImageLinkTargetError):
    """Raised when a valid link points to a missing image file."""


@dataclass(frozen=True)
class CreatedImageLink:
    token: str
    token_hash: str
    view_url: str
    record_path: Path
    relative_path: str
    content_type: str
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class ResolvedImageLink:
    image_path: Path
    content_type: str
    token_hash: str
    link_record: dict[str, Any]


def create_image_link(
    *,
    record_dedupe_key: str,
    relative_path: str,
    content_type: str,
    created_at: datetime | None = None,
    ttl_seconds: int | None = None,
    root: Path | str | None = None,
) -> CreatedImageLink:
    created = _coerce_datetime(created_at)
    expires_at = created + timedelta(seconds=ttl_seconds or _link_ttl_seconds())
    token = secrets.token_urlsafe(32)
    token_hash_value = token_hash(token)
    paths = event_store.ensure_event_store_dirs(
        day=created.strftime("%Y-%m-%d"),
        root=root,
    )
    record_path = paths.links_dir / f"{token_hash_value}.json"
    normalized_relative_path = _validate_relative_path(relative_path)
    record = {
        "version": 1,
        "token_hash": token_hash_value,
        "record_dedupe_key": record_dedupe_key,
        "relative_path": normalized_relative_path,
        "content_type": content_type,
        "created_at": created.isoformat(),
        "expires_at": expires_at.isoformat(),
        "access_count": 0,
        "last_accessed_at": None,
    }
    _atomic_write_json(record_path, record)
    return CreatedImageLink(
        token=token,
        token_hash=token_hash_value,
        view_url=f"{_image_public_base_url().rstrip('/')}/{token}",
        record_path=record_path,
        relative_path=normalized_relative_path,
        content_type=content_type,
        created_at=created,
        expires_at=expires_at,
    )


def resolve_image_link(
    token: str,
    *,
    root: Path | str | None = None,
    now: datetime | None = None,
    touch: bool = True,
) -> ResolvedImageLink:
    cleaned_token = _validate_token(token)
    token_hash_value = token_hash(cleaned_token)
    record_path = _find_link_record(token_hash_value, root=root)
    record = _read_link_record(record_path)
    expires_at = _parse_datetime(str(record.get("expires_at") or ""))
    current_time = _coerce_datetime(now)
    if current_time >= expires_at:
        raise ImageLinkExpiredError("image link expired")

    relative_path = _validate_relative_path(str(record.get("relative_path") or ""))
    image_path = event_store.event_store_root(root) / relative_path
    try:
        event_store.relative_to_root(image_path, root=root)
    except event_store.EventStoreError as exc:
        raise ImageLinkPathError("image target is outside event store root") from exc
    if not image_path.exists() or not image_path.is_file():
        raise ImageLinkFileNotFoundError("image target does not exist")

    if touch:
        record = _touch_link_record(record_path, record, accessed_at=current_time)

    return ResolvedImageLink(
        image_path=image_path,
        content_type=str(record.get("content_type") or "application/octet-stream"),
        token_hash=token_hash_value,
        link_record=record,
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_token(token: str) -> str:
    cleaned = (token or "").strip()
    if not _TOKEN_RE.fullmatch(cleaned):
        raise InvalidImageTokenError("invalid image token")
    return cleaned


def _validate_relative_path(relative_path: str) -> str:
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ImageLinkPathError("invalid image relative path")
    text = candidate.as_posix().strip("/")
    if not text:
        raise ImageLinkPathError("empty image relative path")
    return text


def _find_link_record(
    token_hash_value: str,
    *,
    root: Path | str | None = None,
) -> Path:
    links_root = event_store.event_store_root(root) / "links"
    if not links_root.exists():
        raise ImageLinkNotFoundError("image link not found")
    matches = sorted(links_root.glob(f"*/{token_hash_value}.json"))
    if not matches:
        raise ImageLinkNotFoundError("image link not found")
    return matches[-1]


def _read_link_record(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as exc:
        raise ImageLinkNotFoundError("invalid image link record") from exc
    if not isinstance(payload, dict):
        raise ImageLinkNotFoundError("invalid image link record")
    return payload


def _touch_link_record(
    path: Path,
    record: dict[str, Any],
    *,
    accessed_at: datetime,
) -> dict[str, Any]:
    updated = dict(record)
    updated["access_count"] = int(updated.get("access_count") or 0) + 1
    updated["last_accessed_at"] = accessed_at.isoformat()
    _atomic_write_json(path, updated)
    return updated


def _image_public_base_url() -> str:
    configured = os.environ.get("P6S_EVENT_IMAGE_PUBLIC_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if public_base_url:
        return f"{public_base_url}/api/p6s/event-images/view"
    return "/api/p6s/event-images/view"


def _link_ttl_seconds() -> int:
    value = os.environ.get("P6S_EVENT_IMAGE_LINK_TTL_SECONDS", "86400").strip()
    try:
        return max(1, int(value))
    except ValueError:
        return 86_400


def _coerce_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(_LOCAL_TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=_LOCAL_TZ)
    return value.astimezone(_LOCAL_TZ)


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ImageLinkExpiredError("invalid image link expiry") from exc
    return _coerce_datetime(parsed)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        tmp_path.write_text(text, encoding="utf-8")
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
