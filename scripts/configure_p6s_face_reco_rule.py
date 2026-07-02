"""Audit or minimally enable P6S face recognition rules."""

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
        description="Audit or enable RecoRule/Enable in P6S RecoRuleList.",
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
        help="FaceReco channel id.",
    )
    parser.add_argument(
        "--restore",
        type=Path,
        help="Restore a previously saved RecoRuleList XML backup.",
    )
    return parser.parse_args()


def print_json(label: str, payload: dict) -> None:
    print(f"{label} " + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def parse_xml(text: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(text.strip())
    except ElementTree.ParseError as exc:
        raise SystemExit(f"failed to parse RecoRuleList XML: {exc}") from exc


def child_text(root: ElementTree.Element | None, path: str) -> str:
    if root is None:
        return ""
    found = root.find(path)
    return (found.text or "").strip() if found is not None else ""


def summarize_rules(root: ElementTree.Element) -> list[dict[str, str]]:
    rows = []
    for idx, rule in enumerate(root.findall("RecoRule")):
        face_group = rule.find("FaceGroupList/FaceGroup")
        rows.append(
            {
                "index": str(idx),
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
    return rows


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


def backup_xml(xml_text: str, channel_id: int) -> Path:
    backup_dir = Path(tempfile.gettempdir()) / "camera-face-guard-p6s-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = backup_dir / f"face_reco_{channel_id}_{ts}.xml"
    path.write_text(xml_text, encoding="utf-8")
    return path


def enable_rules(root: ElementTree.Element) -> int:
    rules = root.findall("RecoRule")
    if not rules:
        raise SystemExit("RecoRuleList has no RecoRule nodes")
    changed = 0
    for rule in rules:
        enable = rule.find("Enable")
        if enable is None:
            raise SystemExit("RecoRule is missing first-level Enable node")
        if (enable.text or "").strip().lower() != "true":
            enable.text = "true"
            changed += 1
    return changed


def to_xml(root: ElementTree.Element) -> str:
    body = ElementTree.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" ?>\n' + body


def compare_non_target_fields(before: list[dict[str, str]], after: list[dict[str, str]]) -> list[str]:
    mismatches = []
    if len(before) != len(after):
        return ["rule_count"]
    for old, new in zip(before, after):
        for key, value in old.items():
            if key == "enable":
                continue
            if new.get(key) != value:
                mismatches.append(f"rule[{old['index']}].{key}")
    return mismatches


def restore_xml(client: P6SCameraClient, path: Path, channel_id: int) -> None:
    xml_text = path.read_text(encoding="utf-8")
    parse_xml(xml_text)
    result = client.set_face_reco_rule_list(xml_text, channel_id=channel_id)
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

    result = client.get_face_reco_rule_list(channel_id=args.channel_id)
    assert_request_ok("READ_FAILED", result)
    xml_text = result.get("text", "")
    root = parse_xml(xml_text)
    before = summarize_rules(root)
    print_json("RECO_RULES_BEFORE", {"rule_count": len(before), "rules": before})

    if not args.apply:
        return

    backup_path = backup_xml(xml_text, args.channel_id)
    print_json("BACKUP", {"path": str(backup_path)})
    changed = enable_rules(root)
    patched_xml = to_xml(root)
    write_result = client.set_face_reco_rule_list(
        patched_xml,
        channel_id=args.channel_id,
    )
    assert_request_ok("WRITE_FAILED", write_result)
    status_code = response_status_code(write_result.get("text", ""))
    print_json(
        "WRITE_RESULT",
        {
            "ok": True,
            "http_status_code": write_result.get("status_code"),
            "device_status_code": status_code,
            "changed_rules": changed,
        },
    )
    if status_code and status_code != "0":
        raise SystemExit(f"write returned device statusCode={status_code}")

    verify_result = client.get_face_reco_rule_list(channel_id=args.channel_id)
    assert_request_ok("VERIFY_READ_FAILED", verify_result)
    verify_root = parse_xml(verify_result.get("text", ""))
    after = summarize_rules(verify_root)
    disabled = [row["index"] for row in after if row["enable"].lower() != "true"]
    if disabled:
        raise SystemExit("RecoRule.Enable still false for indexes: " + ",".join(disabled))
    mismatches = compare_non_target_fields(before, after)
    if mismatches:
        raise SystemExit("Non-target fields changed: " + ",".join(mismatches))

    print_json(
        "RECO_RULES_AFTER",
        {
            "ok": True,
            "changed_rules": changed,
            "backup": str(backup_path),
            "rule_count": len(after),
            "rules": after,
        },
    )


if __name__ == "__main__":
    main()
