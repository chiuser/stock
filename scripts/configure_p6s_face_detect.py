"""Audit or minimally enable P6S normal face-detect event settings."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
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
        description="Audit or enable /Pictures/{ChannelID}/FaceDetect safely.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("CAMERA_ENV_FILE", ".env.local"),
        help="Environment file to load before connecting to the camera.",
    )
    parser.add_argument("--apply", action="store_true", help="Write the patch.")
    parser.add_argument(
        "--channel-id",
        type=int,
        default=1,
        help="Camera channel id.",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        help="Restore a previously saved FaceDetect XML backup.",
    )
    parser.add_argument(
        "--print-diff-summary",
        action="store_true",
        help="Print a dry-run summary of the planned patch.",
    )
    return parser.parse_args()


def print_json(label: str, payload: dict) -> None:
    print(f"{label} " + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def parse_xml(text: str) -> ElementTree.Element:
    try:
        root = ElementTree.fromstring(text.strip())
    except ElementTree.ParseError as exc:
        raise SystemExit(f"failed to parse FaceDetect XML: {exc}") from exc
    if root.tag != "FaceDetect":
        raise SystemExit(f"unexpected root tag for FaceDetect XML: {root.tag}")
    return root


def child_text(root: ElementTree.Element | None, path: str) -> str:
    if root is None:
        return ""
    found = root.find(path)
    return (found.text or "").strip() if found is not None else ""


def summarize_face_detect(root: ElementTree.Element) -> dict[str, str]:
    return {
        "enable": child_text(root, "Enable"),
        "enable_overlay": child_text(root, "EnableOverlay"),
        "sensitive": child_text(root, "Senstive"),
        "trigger_push_enable": child_text(root, "Trigger/Push/Enable"),
        "trigger_snapshot_enable": child_text(root, "Trigger/Snapshot/Enable"),
        "trigger_record_enable": child_text(root, "Trigger/Record/Enable"),
        "trigger_beep_alert_enable": child_text(root, "Trigger/BeepAlert/Enable"),
        "trigger_light_alarm_enable": child_text(root, "Trigger/LightAlarm/Enable"),
        "trigger_face_mask_enable": child_text(root, "Trigger/FaceMask/Enable"),
        "schedule_all_day": child_text(root, "Schedule/AllDay"),
    }


def assert_request_ok(label: str, result: dict) -> None:
    if result.get("ok"):
        return
    print_json(
        label,
        {
            "ok": False,
            "status_code": result.get("status_code"),
            "text_preview": " ".join(str(result.get("text", "")).split())[:300],
        },
    )
    raise SystemExit(1)


def response_status_code(text: str) -> str:
    if not text.strip():
        return ""
    try:
        root = ElementTree.fromstring(text.strip())
    except ElementTree.ParseError:
        return ""
    return child_text(root, "statusCode")


def response_message(text: str) -> str:
    if not text.strip():
        return ""
    try:
        root = ElementTree.fromstring(text.strip())
    except ElementTree.ParseError:
        return ""
    return child_text(root, "message")


def backup_xml(xml_text: str, channel_id: int) -> Path:
    backup_dir = Path(tempfile.gettempdir()) / "camera-face-guard-p6s-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = backup_dir / f"face_detect_{channel_id}_{ts}.xml"
    path.write_text(xml_text, encoding="utf-8")
    return path


def to_xml(root: ElementTree.Element) -> str:
    body = ElementTree.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" ?>\n' + body


def enable_face_detect(root: ElementTree.Element) -> int:
    enable = root.find("Enable")
    if enable is None:
        raise SystemExit("FaceDetect XML is missing top-level Enable node")
    if (enable.text or "").strip().lower() == "true":
        return 0
    enable.text = "true"
    return 1


def non_target_mismatches(before: dict[str, str], after: dict[str, str]) -> list[str]:
    mismatches = []
    for key, value in before.items():
        if key == "enable":
            continue
        if after.get(key) != value:
            mismatches.append(key)
    return mismatches


def build_patch(xml_text: str) -> tuple[str, int, dict[str, str], dict[str, str]]:
    root = parse_xml(xml_text)
    before = summarize_face_detect(root)
    changed = enable_face_detect(root)
    patched_xml = to_xml(root)
    after = summarize_face_detect(parse_xml(patched_xml))
    return patched_xml, changed, before, after


def restore_xml(client: P6SCameraClient, path: Path, channel_id: int) -> None:
    xml_text = path.read_text(encoding="utf-8")
    parse_xml(xml_text)
    result = client.set_face_detect(xml_text, channel_id=channel_id)
    assert_request_ok("RESTORE_FAILED", result)
    status_code = response_status_code(result.get("text", ""))
    if status_code and status_code != "0":
        raise SystemExit(f"restore returned device statusCode={status_code}")
    print_json("RESTORE_RESULT", {"ok": True, "backup": str(path)})


def main() -> None:
    args = parse_args()
    load_env_file(Path(args.env_file))
    config = P6SConfig.from_env()
    client = P6SCameraClient(config)

    print_json("CAMERA", config.safe_summary())
    if not config.configured():
        raise SystemExit("P6S camera connection config is incomplete")

    if args.restore:
        restore_xml(client, args.restore, args.channel_id)
        return

    result = client.get_face_detect(channel_id=args.channel_id)
    assert_request_ok("READ_FAILED", result)
    xml_text = result.get("text", "")
    before_root = parse_xml(xml_text)
    before = summarize_face_detect(before_root)
    print_json("FACE_DETECT_BEFORE", before)

    patched_xml, changed, patch_before, patch_after = build_patch(xml_text)
    mismatches = non_target_mismatches(patch_before, patch_after)
    if args.print_diff_summary or args.apply:
        print_json(
            "PATCH_DIFF_SUMMARY",
            {
                "changed_fields": ["Enable"] if changed else [],
                "changed_count": changed,
                "non_target_mismatches": mismatches,
                "before": patch_before,
                "after": patch_after,
            },
        )
    if mismatches:
        raise SystemExit("Planned patch changes non-target fields: " + ",".join(mismatches))

    if not args.apply:
        return

    backup_path = backup_xml(xml_text, args.channel_id)
    print_json("BACKUP", {"path": str(backup_path)})
    write_result = client.set_face_detect(patched_xml, channel_id=args.channel_id)
    assert_request_ok("WRITE_FAILED", write_result)
    status_code = response_status_code(write_result.get("text", ""))
    print_json(
        "WRITE_RESULT",
        {
            "http_status": write_result.get("status_code"),
            "device_status_code": status_code,
            "device_message": response_message(write_result.get("text", "")),
        },
    )
    if status_code and status_code != "0":
        raise SystemExit(f"write returned device statusCode={status_code}")

    after_result = client.get_face_detect(channel_id=args.channel_id)
    assert_request_ok("VERIFY_READ_FAILED", after_result)
    after = summarize_face_detect(parse_xml(after_result.get("text", "")))
    print_json("FACE_DETECT_AFTER", after)

    if after.get("enable", "").lower() != "true":
        raise SystemExit("FaceDetect Enable did not persist as true")
    verify_mismatches = non_target_mismatches(before, after)
    if verify_mismatches:
        raise SystemExit(
            "FaceDetect non-target fields changed after write: "
            + ",".join(verify_mismatches)
        )


if __name__ == "__main__":
    main()
