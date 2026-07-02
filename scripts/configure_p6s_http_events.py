"""Configure and audit P6S HTTP event push settings.

The script is intentionally safe-by-default: without --apply it only reads the
camera state and prints redacted summaries.  It never prints camera passwords or
the full P6S event callback secret.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.p6s_camera import P6SCameraClient, P6SConfig


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit or configure P6S HTTP event push settings.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("CAMERA_ENV_FILE", ".env.local"),
        help="Environment file to load before connecting to the camera.",
    )
    parser.add_argument("--apply", action="store_true", help="Write HTTP config.")
    parser.add_argument("--test", action="store_true", help="Run camera HTTP test.")
    parser.add_argument("--host", help="Public server host for camera callbacks.")
    parser.add_argument("--port", type=int, help="Public server port.")
    parser.add_argument("--protocol", choices=["http", "https"], help="Protocol.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="DataTransfer2ServerTimeout value in seconds.",
    )
    parser.add_argument(
        "--no-cache-events",
        action="store_true",
        help="Disable camera-side event cache.",
    )
    return parser.parse_args()


def target_from_env(args: argparse.Namespace) -> tuple[str, int, str, str]:
    public_base_url = os.environ.get("PUBLIC_BASE_URL", "").strip()
    parsed = urlparse(public_base_url if "://" in public_base_url else "")
    protocol = args.protocol or parsed.scheme or "http"
    host = args.host or parsed.hostname or "82.156.198.180"
    port = args.port or parsed.port or (443 if protocol == "https" else 80)
    secret = os.environ.get("P6S_EVENT_SECRET", "").strip()
    if not secret:
        raise SystemExit("P6S_EVENT_SECRET is missing")
    url_path = f"/api/p6s/events/{secret}"
    return host, port, protocol, url_path


def parse_xml(text: str) -> ElementTree.Element | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return ElementTree.fromstring(stripped)
    except ElementTree.ParseError:
        return None


def child_text(root: ElementTree.Element | None, path: str) -> str:
    if root is None:
        return ""
    found = root.find(path)
    return (found.text or "").strip() if found is not None else ""


def children(root: ElementTree.Element | None, path: str) -> list[ElementTree.Element]:
    if root is None:
        return []
    return list(root.findall(path))


def redact(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "<P6S_EVENT_SECRET>")
    return text


def preview_text(text: str, secret: str, limit: int = 300) -> str:
    compact = " ".join(text.split())
    return redact(compact[:limit], secret)


def print_json(label: str, payload: dict) -> None:
    print(f"{label} " + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def summarize_http_config(
    text: str,
    secret: str,
    expected_path: str | None = None,
) -> dict:
    root = parse_xml(text)
    url_path = child_text(root, "URLPath")
    return {
        "enable": child_text(root, "Enable"),
        "protocol": child_text(root, "Protocol"),
        "host": child_text(root, "Host"),
        "port": child_text(root, "Port"),
        "auth_mode": child_text(root, "AuthMode"),
        "cache_event_enable": child_text(root, "CacheEventEnable"),
        "timeout_seconds": child_text(root, "DataTransfer2ServerTimeout"),
        "url_path": redact(url_path, secret),
        "url_path_matches": bool(expected_path and url_path == expected_path),
    }


def summarize_http_test(text: str, secret: str) -> dict:
    root = parse_xml(text)
    return {
        "status_code": child_text(root, "StatusCode"),
        "event_id": child_text(root, "EventID"),
        "time": child_text(root, "Time"),
        "has_info": bool(child_text(root, "Info")),
        "preview": preview_text(text, secret),
    }


def summarize_event_push_mode(text: str) -> dict:
    root = parse_xml(text)
    return {"mqtt_push_mode": child_text(root, "MQTTPushMode")}


def summarize_ai_event_cfg(text: str) -> dict:
    root = parse_xml(text)
    return {
        "enable": child_text(root, "Enable"),
        "http_type": child_text(root, "HttpType"),
        "root": root.tag if root is not None else "",
    }


def summarize_face_snapshot_cfg(text: str) -> dict:
    root = parse_xml(text)
    return {
        "enable": child_text(root, "Enable"),
        "show_face_frame": child_text(root, "ShowFaceFrame"),
        "is_capture_background": child_text(root, "IsCaptureBackground"),
        "is_push_face_features": child_text(root, "IsPushFaceFeatures"),
        "trigger_push_enable": child_text(root, "Trigger/Push/Enable"),
        "trigger_snapshot_enable": child_text(root, "Trigger/Snapshot/Enable"),
        "schedule_all_day": child_text(root, "Schedule/AllDay"),
    }


def summarize_face_reco_rules(text: str) -> dict:
    root = parse_xml(text)
    rules = []
    for rule in children(root, "RecoRule"):
        face_group = rule.find("FaceGroupList/FaceGroup")
        rules.append(
            {
                "enable": child_text(rule, "Enable"),
                "recognition_rule": child_text(rule, "RecognitionRule"),
                "compare_limit": child_text(rule, "CompareLimit"),
                "control_personnel_type": child_text(
                    rule,
                    "FaceGroupList/ControlPersonnelType",
                ),
                "face_group_enable": child_text(face_group, "Enable"),
                "face_group_name": child_text(face_group, "GroupName"),
                "trigger_push_enable": child_text(rule, "Trigger/Push/Enable"),
                "trigger_snapshot_enable": child_text(rule, "Trigger/Snapshot/Enable"),
            }
        )
    return {"rule_count": len(rules), "rules": rules[:5]}


def ensure_ok(label: str, result: dict, secret: str) -> None:
    if result.get("ok"):
        return
    print_json(
        label,
        {
            "ok": False,
            "status_code": result.get("status_code"),
            "text": preview_text(str(result.get("text", "")), secret),
        },
    )
    raise SystemExit(1)


def print_result(label: str, result: dict, secret: str, summary: dict | None) -> None:
    payload = {
        "ok": result.get("ok"),
        "status_code": result.get("status_code"),
    }
    if summary is not None:
        payload["summary"] = summary
    elif not result.get("ok"):
        payload["text"] = preview_text(str(result.get("text", "")), secret)
    print_json(label, payload)


def assert_http_config_matches(
    summary: dict,
    host: str,
    port: int,
    protocol: str,
) -> None:
    mismatches = []
    expected = {
        "enable": "true",
        "protocol": protocol,
        "host": host,
        "port": str(port),
        "auth_mode": "none",
        "cache_event_enable": "true",
    }
    for key, value in expected.items():
        if str(summary.get(key, "")).lower() != value.lower():
            mismatches.append(key)
    if not summary.get("url_path_matches"):
        mismatches.append("url_path")
    if mismatches:
        raise SystemExit("HTTP config mismatch: " + ",".join(sorted(mismatches)))


def main() -> None:
    args = parse_args()
    load_env_file(Path(args.env_file))
    config = P6SConfig.from_env()
    secret = os.environ.get("P6S_EVENT_SECRET", "").strip()
    host, port, protocol, url_path = target_from_env(args)
    client = P6SCameraClient(config)

    print_json("CAMERA", config.safe_summary())
    if not config.configured():
        raise SystemExit("P6S camera connection config is incomplete")

    current = client.get_http_event_server_config()
    ensure_ok("HTTP_CONFIG_READ_FAILED", current, secret)
    print_result(
        "HTTP_CONFIG_BEFORE",
        current,
        secret,
        summarize_http_config(current.get("text", ""), secret, expected_path=url_path),
    )

    if args.apply:
        write_result = client.set_http_event_server_config(
            host=host,
            port=port,
            protocol=protocol,
            url_path=url_path,
            timeout_seconds=args.timeout,
            cache_event_enable=not args.no_cache_events,
        )
        ensure_ok("HTTP_CONFIG_WRITE_FAILED", write_result, secret)
        print_result("HTTP_CONFIG_WRITE", write_result, secret, {"written": True})

        after = client.get_http_event_server_config()
        ensure_ok("HTTP_CONFIG_VERIFY_READ_FAILED", after, secret)
        after_summary = summarize_http_config(
            after.get("text", ""),
            secret,
            expected_path=url_path,
        )
        assert_http_config_matches(after_summary, host, port, protocol)
        print_result("HTTP_CONFIG_AFTER", after, secret, after_summary)

    event_push = client.get_event_push_mode()
    print_result(
        "EVENT_PUSH_MODE",
        event_push,
        secret,
        summarize_event_push_mode(event_push.get("text", ""))
        if event_push.get("ok")
        else None,
    )

    ai_event = client.get_ai_event_cfg()
    print_result(
        "AI_EVENT_CFG",
        ai_event,
        secret,
        summarize_ai_event_cfg(ai_event.get("text", "")) if ai_event.get("ok") else None,
    )

    face_snapshot = client.get_face_snapshot_cfg()
    print_result(
        "FACE_SNAPSHOT_CFG",
        face_snapshot,
        secret,
        summarize_face_snapshot_cfg(face_snapshot.get("text", ""))
        if face_snapshot.get("ok")
        else None,
    )

    reco_rules = client.get_face_reco_rule_list()
    print_result(
        "FACE_RECO_RULES",
        reco_rules,
        secret,
        summarize_face_reco_rules(reco_rules.get("text", ""))
        if reco_rules.get("ok")
        else None,
    )

    if args.test:
        test_text = "camera-face-guard-http-test-" + datetime.now().strftime(
            "%Y%m%d%H%M%S",
        )
        test_result = client.test_http_event_server(test_text)
        ensure_ok("HTTP_EVENT_SERVER_TEST_FAILED", test_result, secret)
        print_result(
            "HTTP_EVENT_SERVER_TEST",
            test_result,
            secret,
            summarize_http_test(test_result.get("text", ""), secret),
        )


if __name__ == "__main__":
    main()
