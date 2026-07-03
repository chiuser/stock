"""Feishu notification helpers for camera events."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass(frozen=True)
class FeishuConfig:
    webhook_url: str
    webhook_secret: str
    app_id: str
    app_secret: str

    @classmethod
    def from_env(cls) -> "FeishuConfig":
        return cls(
            webhook_url=os.environ.get("FEISHU_WEBHOOK_URL", "").strip(),
            webhook_secret=os.environ.get("FEISHU_WEBHOOK_SECRET", "").strip(),
            app_id=os.environ.get("FEISHU_APP_ID", "").strip(),
            app_secret=os.environ.get("FEISHU_APP_SECRET", "").strip(),
        )

    def safe_summary(self) -> dict[str, bool]:
        return {
            "has_webhook": bool(self.webhook_url),
            "has_webhook_secret": bool(self.webhook_secret),
            "has_app_id": bool(self.app_id),
            "has_app_secret": bool(self.app_secret),
            "can_sign_webhook": bool(self.webhook_url and self.webhook_secret),
            "can_upload_image": bool(
                self.webhook_url and self.app_id and self.app_secret
            ),
        }


def send_text(text: str, config: FeishuConfig | None = None) -> dict[str, Any]:
    cfg = config or FeishuConfig.from_env()
    return _send_webhook_payload(
        {"msg_type": "text", "content": {"text": text}},
        cfg,
    )


def send_post(
    title: str,
    lines: list[list[dict[str, str]]],
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    cfg = config or FeishuConfig.from_env()
    return _send_webhook_payload(build_post_payload(title, lines), cfg)


def build_post_payload(
    title: str,
    lines: list[list[dict[str, str]]],
) -> dict[str, Any]:
    """Build a Feishu post payload without sending it."""

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": title,
                    "content": lines,
                }
            }
        },
    }


def upload_image(image_path: Path, config: FeishuConfig | None = None) -> dict[str, Any]:
    cfg = config or FeishuConfig.from_env()
    if not (cfg.app_id and cfg.app_secret):
        return {"ok": False, "text": "FEISHU_APP_ID/FEISHU_APP_SECRET is not configured"}

    token_result = _tenant_access_token(cfg)
    if not token_result["ok"]:
        return token_result

    try:
        with image_path.open("rb") as image_file:
            response = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {token_result['tenant_access_token']}"},
                data={"image_type": "message"},
                files={"image": image_file},
                timeout=15,
            )
        payload = response.json()
        image_key = (payload.get("data") or {}).get("image_key", "")
        return {
            "ok": response.ok and bool(image_key),
            "status_code": response.status_code,
            "image_key": image_key,
            "text": response.text,
        }
    except (requests.RequestException, OSError, ValueError) as exc:
        return {"ok": False, "status_code": None, "text": str(exc)}


def send_image(image_key: str, config: FeishuConfig | None = None) -> dict[str, Any]:
    cfg = config or FeishuConfig.from_env()
    return _send_webhook_payload(
        {"msg_type": "image", "content": {"image_key": image_key}},
        cfg,
    )


def notify_known_face(
    *,
    name: str,
    person_id: str,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    role_name: str = "",
    title: str = "",
    storage_path: str | None = None,
    view_url: str | None = None,
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    """Notify Feishu about a successfully matched face."""

    cfg = config or FeishuConfig.from_env()
    return _send_webhook_payload(
        build_known_face_post(
            name=name,
            person_id=person_id,
            device_sn=device_sn,
            event_time=event_time,
            event_id=event_id,
            role_name=role_name,
            title=title,
            storage_path=storage_path,
            view_url=view_url,
        ),
        cfg,
    )


def build_known_face_post(
    *,
    name: str,
    person_id: str,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    role_name: str = "",
    title: str = "",
    storage_path: str | None = None,
    view_url: str | None = None,
) -> dict[str, Any]:
    """Build the post payload for a successfully matched face."""

    lines = [
        _text_line("姓名", name),
        _text_line("人员 ID", person_id),
        _text_line("设备", device_sn or "unknown"),
        _text_line("时间", event_time or "unknown"),
        _text_line("事件 ID", event_id or "unknown"),
    ]
    if role_name:
        # Put the user-facing role at the end so existing field order stays stable.
        lines.append(_text_line("身份类型", role_name))
    if storage_path:
        lines.append(_text_line("保存位置", storage_path))
    if view_url:
        lines.append(_link_line("查看图片", view_url))
    return build_post_payload(title or "人员入场提醒", lines)


def notify_unknown_face(
    *,
    image_path: Path | None,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    storage_path: str | None = None,
    view_url: str | None = None,
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    """Notify Feishu about an unknown face and include a link when possible."""

    cfg = config or FeishuConfig.from_env()
    post_payload = build_unknown_face_post(
        image_path=image_path,
        device_sn=device_sn,
        event_time=event_time,
        event_id=event_id,
        storage_path=storage_path,
        view_url=view_url,
    )

    results: list[dict[str, Any]] = [_send_webhook_payload(post_payload, cfg)]

    if image_path and image_path.exists() and cfg.app_id and cfg.app_secret:
        upload_result = upload_image(image_path, cfg)
        results.append({"step": "upload_image", **upload_result})
        if upload_result.get("ok") and upload_result.get("image_key"):
            results.append(
                {
                    "step": "send_image",
                    **send_image(upload_result["image_key"], cfg),
                }
            )

    return {"ok": any(r.get("ok") for r in results), "results": results}


def build_unknown_face_post(
    *,
    image_path: Path | None,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    storage_path: str | None = None,
    view_url: str | None = None,
) -> dict[str, Any]:
    """Build the post payload for an unknown face."""

    resolved_storage_path = storage_path or (str(image_path) if image_path else "")
    lines = [
        _text_line("设备", device_sn or "unknown"),
        _text_line("时间", event_time or "unknown"),
        _text_line("事件 ID", event_id or "unknown"),
    ]
    if resolved_storage_path:
        lines.append(_text_line("保存位置", resolved_storage_path))
    if view_url:
        lines.append(_link_line("查看图片", view_url))
    return build_post_payload("发现陌生人入场", lines)


def notify_event_error(
    *,
    message: str,
    device_sn: str = "",
    event_time: str = "",
    event_id: str | int | None = None,
    raw_event_path: str = "",
    storage_path: str | None = None,
    view_url: str | None = None,
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    """Notify Feishu about an event handling error without exposing stack traces."""

    cfg = config or FeishuConfig.from_env()
    return _send_webhook_payload(
        build_event_error_post(
            message=message,
            device_sn=device_sn,
            event_time=event_time,
            event_id=event_id,
            raw_event_path=raw_event_path,
            storage_path=storage_path,
            view_url=view_url,
        ),
        cfg,
    )


def build_event_error_post(
    *,
    message: str,
    device_sn: str = "",
    event_time: str = "",
    event_id: str | int | None = None,
    raw_event_path: str = "",
    storage_path: str | None = None,
    view_url: str | None = None,
) -> dict[str, Any]:
    """Build the post payload for an event handling error."""

    lines = [
        _text_line("问题", message),
        _text_line("设备", device_sn or "unknown"),
        _text_line("时间", event_time or "unknown"),
        _text_line("事件 ID", event_id or "unknown"),
    ]
    if raw_event_path:
        lines.append(_text_line("原始事件", raw_event_path))
    if storage_path:
        lines.append(_text_line("保存位置", storage_path))
    if view_url:
        lines.append(_link_line("查看图片", view_url))
    return build_post_payload("人脸识别事件处理异常", lines)


def _tenant_access_token(config: FeishuConfig) -> dict[str, Any]:
    try:
        response = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": config.app_id, "app_secret": config.app_secret},
            timeout=10,
        )
        payload = response.json()
        token = payload.get("tenant_access_token", "")
        return {
            "ok": response.ok and bool(token),
            "status_code": response.status_code,
            "tenant_access_token": token,
            "text": response.text,
        }
    except (requests.RequestException, ValueError) as exc:
        return {"ok": False, "status_code": None, "text": str(exc)}


def _send_webhook_payload(
    payload: dict[str, Any],
    config: FeishuConfig,
) -> dict[str, Any]:
    if not config.webhook_url:
        return {"ok": False, "text": "FEISHU_WEBHOOK_URL is not configured"}

    try:
        response = requests.post(
            config.webhook_url,
            json=_with_signature(payload, config),
            timeout=10,
        )
        return {
            "ok": response.ok,
            "status_code": response.status_code,
            "text": response.text,
        }
    except requests.RequestException as exc:
        return {"ok": False, "status_code": None, "text": str(exc)}


def _with_signature(payload: dict[str, Any], config: FeishuConfig) -> dict[str, Any]:
    if not config.webhook_secret:
        return dict(payload)

    timestamp = str(int(time.time()))
    string_to_sign = f"{timestamp}\n{config.webhook_secret}"
    signature = base64.b64encode(
        hmac.new(string_to_sign.encode("utf-8"), b"", hashlib.sha256).digest()
    ).decode("utf-8")
    signed_payload = dict(payload)
    signed_payload["timestamp"] = timestamp
    signed_payload["sign"] = signature
    return signed_payload


def _text_line(label: str, value: Any) -> list[dict[str, str]]:
    return [{"tag": "text", "text": f"{label}: {value}"}]


def _link_line(text: str, href: str) -> list[dict[str, str]]:
    return [{"tag": "a", "text": text, "href": href}]
