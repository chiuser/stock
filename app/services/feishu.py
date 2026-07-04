"""Feishu notification helpers for camera events."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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

    @classmethod
    def from_face_recheck_shadow_env(cls) -> "FeishuConfig":
        return cls(
            webhook_url=os.environ.get("FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_URL", "").strip(),
            webhook_secret=os.environ.get("FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_SECRET", "").strip(),
            app_id="",
            app_secret="",
        )


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


def notify_face_recheck_shadow(
    *,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    camera_result: str,
    camera_person_summary: dict[str, Any] | None,
    recheck_result: dict[str, Any],
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
    config: FeishuConfig | None = None,
) -> dict[str, Any]:
    """Send InsightFace shadow comparison to the dedicated Feishu bot."""

    cfg = config or FeishuConfig.from_face_recheck_shadow_env()
    if not cfg.webhook_url:
        return {
            "ok": True,
            "skipped": True,
            "reason": "face recheck shadow webhook is not configured",
        }
    return _send_webhook_payload(
        build_face_recheck_shadow_post(
            device_sn=device_sn,
            event_time=event_time,
            event_id=event_id,
            camera_result=camera_result,
            camera_person_summary=camera_person_summary,
            recheck_result=recheck_result,
            background_view_url=background_view_url,
            capture_view_url=capture_view_url,
        ),
        cfg,
    )


def build_face_recheck_shadow_post(
    *,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    camera_result: str,
    camera_person_summary: dict[str, Any] | None,
    recheck_result: dict[str, Any],
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
) -> dict[str, Any]:
    """Build a shadow-only InsightFace comparison post."""

    selected_face = recheck_result.get("selected_face") or {}
    gallery_match = recheck_result.get("gallery_match") or {}
    thresholds = recheck_result.get("thresholds") or {}
    lines = [
        _text_line("事件时间", event_time or "unknown"),
        _text_line("发送时间", _now_text()),
        _text_line("设备", device_sn or "unknown"),
        _text_line("事件 ID", event_id or "unknown"),
        _text_line("摄像头结果", camera_result or "unknown"),
        _text_line("摄像头人员", _camera_person_text(camera_person_summary)),
        _text_line("InsightFace 模式", recheck_result.get("mode") or "unknown"),
        _text_line("InsightFace 状态", recheck_result.get("status") or "unknown"),
        _text_line("InsightFace 建议", recheck_result.get("decision") or "unknown"),
        _text_line("过滤原因", recheck_result.get("reason") or "unknown"),
        _text_line("检测人脸数", recheck_result.get("face_count", 0)),
        _text_line("是否检测到人脸", "是" if recheck_result.get("face_count", 0) else "否"),
    ]
    if selected_face:
        lines.extend(
            [
                _text_line("检测分数", selected_face.get("det_score", "unknown")),
                _text_line("检测分阈值", _min_threshold_text(thresholds.get("det_score_threshold"))),
                _text_line(
                    "人脸尺寸",
                    f"{selected_face.get('width', 'unknown')}x{selected_face.get('height', 'unknown')}",
                ),
                _text_line(
                    "尺寸阈值",
                    _face_size_threshold_text(
                        thresholds.get("min_face_width"),
                        thresholds.get("min_face_height"),
                    ),
                ),
                _text_line("模糊分数", selected_face.get("blur_score", "unknown")),
                _text_line("模糊阈值", _min_threshold_text(thresholds.get("blur_threshold"))),
                _text_line("侧脸分数", selected_face.get("frontal_score", "unknown")),
                _text_line("侧脸阈值", _max_threshold_text(thresholds.get("frontal_max_yaw_score"))),
                _text_line("质量标记", ", ".join(selected_face.get("quality_flags") or []) or "无"),
            ]
        )
    if gallery_match:
        lines.append(
            _text_line(
                "Gallery 命中",
                (
                    f"{gallery_match.get('name', '')} / "
                    f"{gallery_match.get('person_type', '')} / "
                    f"{gallery_match.get('person_id', '')} / "
                    f"{gallery_match.get('similarity', '')}"
                ).strip(" /"),
            )
        )
        lines.extend(
            [
                _text_line(
                    "Gallery 阈值",
                    _gallery_threshold_text(
                        thresholds.get("similarity_threshold"),
                        thresholds.get("similarity_margin"),
                    ),
                ),
                _text_line(
                    "Gallery 第二名分数",
                    gallery_match.get("second_similarity", "无"),
                ),
                _text_line("Gallery 是否通过", gallery_match.get("accepted", False)),
                _text_line(
                    "Gallery 候选集",
                    _gallery_candidates_text(gallery_match.get("candidates") or []),
                ),
                _text_line(
                    "结果对齐",
                    gallery_match.get("camera_identity_status", "not_compared"),
                ),
            ]
        )
    else:
        lines.append(_text_line("Gallery 命中", "未启用"))
    _append_image_links(
        lines,
        background_view_url=background_view_url,
        capture_view_url=capture_view_url,
    )
    return build_post_payload("InsightFace Shadow 对比", lines)


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
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
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
            background_view_url=background_view_url,
            capture_view_url=capture_view_url,
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
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
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
    _append_image_links(
        lines,
        view_url=view_url,
        background_view_url=background_view_url,
        capture_view_url=capture_view_url,
    )
    return build_post_payload(title or "人员入场提醒", lines)


def notify_unknown_face(
    *,
    image_path: Path | None,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    storage_path: str | None = None,
    view_url: str | None = None,
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
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
        background_view_url=background_view_url,
        capture_view_url=capture_view_url,
    )

    results: list[dict[str, Any]] = [
        {"step": "send_post", **_send_webhook_payload(post_payload, cfg)}
    ]

    return {"ok": any(r.get("ok") for r in results), "results": results}


def build_unknown_face_post(
    *,
    image_path: Path | None,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    storage_path: str | None = None,
    view_url: str | None = None,
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
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
    _append_image_links(
        lines,
        view_url=view_url,
        background_view_url=background_view_url,
        capture_view_url=capture_view_url,
    )
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
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
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
            background_view_url=background_view_url,
            capture_view_url=capture_view_url,
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
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
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
    _append_image_links(
        lines,
        view_url=view_url,
        background_view_url=background_view_url,
        capture_view_url=capture_view_url,
    )
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


def _now_text() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _camera_person_text(person: dict[str, Any] | None) -> str:
    if not person:
        return "陌生人/无"
    name = str(person.get("name") or person.get("person_name") or "").strip()
    person_id = str(person.get("id") or person.get("person_id") or "").strip()
    role = str(person.get("role_name") or person.get("role") or "").strip()
    parts = [part for part in (name, person_id, role) if part]
    return " / ".join(parts) if parts else "未知"


def _text_line(label: str, value: Any) -> list[dict[str, str]]:
    return [{"tag": "text", "text": f"{label}: {value}"}]


def _min_threshold_text(value: Any) -> str:
    return f">= {value}" if value not in (None, "") else "unknown"


def _max_threshold_text(value: Any) -> str:
    return f"<= {value}" if value not in (None, "") else "unknown"


def _face_size_threshold_text(width: Any, height: Any) -> str:
    if width in (None, "") or height in (None, ""):
        return "unknown"
    return f">= {width}x{height}"


def _gallery_threshold_text(similarity: Any, margin: Any) -> str:
    if similarity in (None, "") and margin in (None, ""):
        return "unknown"
    return (
        f"相似度 {_min_threshold_text(similarity)}；"
        f"领先第二名 {_min_threshold_text(margin)}"
    )


def _gallery_candidates_text(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "无"
    items: list[str] = []
    for candidate in candidates[:5]:
        name = str(candidate.get("name") or "未知").strip()
        person_type = str(candidate.get("person_type") or "unknown").strip()
        person_id = str(candidate.get("person_id") or candidate.get("credential_no") or "").strip()
        group_name = str(candidate.get("group_name") or "").strip()
        similarity = candidate.get("similarity", "unknown")
        rank = candidate.get("rank", len(items) + 1)
        identity = " / ".join(part for part in (name, person_type, group_name, person_id) if part)
        items.append(f"{rank}. {identity} / {similarity}")
    return "; ".join(items)


def _link_line(text: str, href: str) -> list[dict[str, str]]:
    return [{"tag": "a", "text": text, "href": href}]


def _append_image_links(
    lines: list[list[dict[str, str]]],
    *,
    view_url: str | None = None,
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
) -> None:
    appended = False
    if background_view_url:
        lines.append(_link_line("查看背景全图", background_view_url))
        appended = True
    if capture_view_url:
        lines.append(_link_line("查看人脸图", capture_view_url))
        appended = True
    if view_url and not appended:
        lines.append(_link_line("查看图片", view_url))
