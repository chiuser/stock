"""Audit or switch the P6S algorithm-store mode safely."""

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


ALGORITHM_TYPES = ("Unknown", "IntelligentAlert", "FaceCapture", "FaceRecognition")


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
        description="Audit or switch /System/AlgorithmStoreCfg safely.",
    )
    parser.add_argument(
        "--env-file",
        default=os.environ.get("CAMERA_ENV_FILE", ".env.local"),
        help="Environment file to load before connecting to the camera.",
    )
    parser.add_argument(
        "--target",
        choices=ALGORITHM_TYPES,
        default="FaceRecognition",
        help="AlgorithmType to write when --apply is used.",
    )
    parser.add_argument("--apply", action="store_true", help="Write the patch.")
    parser.add_argument(
        "--restore",
        type=Path,
        help="Restore a previously saved AlgorithmStoreCfg XML backup.",
    )
    parser.add_argument(
        "--print-diff-summary",
        action="store_true",
        help="Print a dry-run summary of the planned patch.",
    )
    return parser.parse_args()


def print_json(label: str, payload: dict) -> None:
    print(f"{label} " + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def child_text(root: ElementTree.Element | None, path: str) -> str:
    if root is None:
        return ""
    found = root.find(path)
    return (found.text or "").strip() if found is not None else ""


def parse_xml(text: str, expected_root: str | None = None) -> ElementTree.Element:
    try:
        root = ElementTree.fromstring(text.strip())
    except ElementTree.ParseError as exc:
        raise SystemExit(f"failed to parse XML: {exc}") from exc
    if expected_root and root.tag != expected_root:
        raise SystemExit(f"unexpected root tag: {root.tag}; expected {expected_root}")
    return root


def parse_algorithm_store_xml(text: str) -> ElementTree.Element:
    return parse_xml(text, expected_root="AlgorithmStoreCfg")


def summarize_algorithm_store(root: ElementTree.Element) -> dict[str, object]:
    return {
        "root": root.tag,
        "root_attrs": dict(root.attrib),
        "algorithm_type": child_text(root, "AlgorithmType"),
    }


def summarize_face_reco_base(root: ElementTree.Element) -> dict[str, str]:
    return {
        "enable_recognition": child_text(root, "EnableRecognition"),
        "overlay_human_box": child_text(root, "OverlayHumanBox"),
        "senstive": child_text(root, "Senstive"),
    }


def summarize_face_snapshot(root: ElementTree.Element) -> dict[str, str]:
    return {
        "enable": child_text(root, "Enable"),
        "trigger_push_enable": child_text(root, "Trigger/Push/Enable"),
        "trigger_snapshot_enable": child_text(root, "Trigger/Snapshot/Enable"),
        "show_face_frame": child_text(root, "ShowFaceFrame"),
        "schedule_all_day": child_text(root, "Schedule/AllDay"),
    }


def summarize_reco_rule(root: ElementTree.Element) -> dict[str, object]:
    first_rule = root.find("RecoRule")
    return {
        "rule_count": len(root.findall("RecoRule")),
        "first_rule_enable": child_text(first_rule, "Enable"),
        "recognition_rule": child_text(first_rule, "RecognitionRule"),
        "control_personnel_type": child_text(
            first_rule,
            "FaceGroupList/ControlPersonnelType",
        ),
        "trigger_push_enable": child_text(first_rule, "Trigger/Push/Enable"),
        "trigger_snapshot_enable": child_text(first_rule, "Trigger/Snapshot/Enable"),
    }


def summarize_face_detect(root: ElementTree.Element) -> dict[str, str]:
    return {
        "enable": child_text(root, "Enable"),
        "trigger_push_enable": child_text(root, "Trigger/Push/Enable"),
        "trigger_snapshot_enable": child_text(root, "Trigger/Snapshot/Enable"),
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


def backup_xml(xml_text: str) -> Path:
    backup_dir = Path(tempfile.gettempdir()) / "camera-face-guard-p6s-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    path = backup_dir / f"algorithm_store_{ts}.xml"
    path.write_text(xml_text, encoding="utf-8")
    return path


def to_xml(root: ElementTree.Element) -> str:
    body = ElementTree.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8" ?>\n' + body


def set_algorithm_type(root: ElementTree.Element, target: str) -> int:
    algorithm_type = root.find("AlgorithmType")
    if algorithm_type is None:
        raise SystemExit("AlgorithmStoreCfg XML is missing AlgorithmType node")
    if (algorithm_type.text or "").strip() == target:
        return 0
    algorithm_type.text = target
    return 1


def non_target_mismatches(
    before_root: ElementTree.Element,
    after_root: ElementTree.Element,
) -> list[str]:
    mismatches = []
    if before_root.tag != after_root.tag:
        mismatches.append("root")
    if before_root.attrib != after_root.attrib:
        mismatches.append("root_attrs")

    def non_target_children(root: ElementTree.Element) -> list[tuple[str, dict, str]]:
        return [
            (child.tag, dict(child.attrib), (child.text or "").strip())
            for child in list(root)
            if child.tag != "AlgorithmType"
        ]

    if non_target_children(before_root) != non_target_children(after_root):
        mismatches.append("children_except_algorithm_type")
    return mismatches


def build_patch(
    xml_text: str,
    target: str,
) -> tuple[str, int, dict[str, object], dict[str, object], list[str]]:
    root = parse_algorithm_store_xml(xml_text)
    before_root = parse_algorithm_store_xml(xml_text)
    before = summarize_algorithm_store(root)
    changed = set_algorithm_type(root, target)
    patched_xml = to_xml(root)
    after_root = parse_algorithm_store_xml(patched_xml)
    after = summarize_algorithm_store(after_root)
    mismatches = non_target_mismatches(before_root, after_root)
    return patched_xml, changed, before, after, mismatches


def read_required_xml(
    label: str,
    result: dict,
    expected_root: str | None = None,
) -> ElementTree.Element:
    assert_request_ok(label, result)
    return parse_xml(result.get("text", ""), expected_root=expected_root)


def read_subconfig_summaries(client: P6SCameraClient) -> dict[str, dict]:
    face_reco_base = read_required_xml(
        "READ_FACE_RECO_BASE_FAILED",
        client.get_face_reco_base_config(),
        expected_root="FaceBaseConfig",
    )
    face_snapshot = read_required_xml(
        "READ_FACE_SNAPSHOT_FAILED",
        client.get_face_snapshot_cfg(),
        expected_root="AIFaceSnapshotCfg",
    )
    reco_rule = read_required_xml(
        "READ_RECO_RULE_FAILED",
        client.get_face_reco_rule_list(),
        expected_root="RecoRuleList",
    )
    face_detect = read_required_xml(
        "READ_FACE_DETECT_FAILED",
        client.get_face_detect(),
        expected_root="FaceDetect",
    )
    return {
        "face_reco_base": summarize_face_reco_base(face_reco_base),
        "face_snapshot": summarize_face_snapshot(face_snapshot),
        "face_reco_rule": summarize_reco_rule(reco_rule),
        "face_detect": summarize_face_detect(face_detect),
    }


def assert_key_subconfigs_enabled(summary: dict[str, dict]) -> None:
    checks = {
        "face_reco_base.enable_recognition": summary["face_reco_base"].get(
            "enable_recognition",
        ),
        "face_snapshot.enable": summary["face_snapshot"].get("enable"),
        "face_snapshot.trigger_push_enable": summary["face_snapshot"].get(
            "trigger_push_enable",
        ),
        "face_reco_rule.trigger_push_enable": summary["face_reco_rule"].get(
            "trigger_push_enable",
        ),
        "face_reco_rule.trigger_snapshot_enable": summary["face_reco_rule"].get(
            "trigger_snapshot_enable",
        ),
    }
    disabled = [key for key, value in checks.items() if str(value).lower() != "true"]
    if disabled:
        raise SystemExit("Key face subconfigs are not enabled: " + ",".join(disabled))


def restore_xml(client: P6SCameraClient, path: Path) -> None:
    xml_text = path.read_text(encoding="utf-8")
    backup_root = parse_algorithm_store_xml(xml_text)
    result = client.set_algorithm_store_cfg(xml_text)
    assert_request_ok("RESTORE_FAILED", result)
    status_code = response_status_code(result.get("text", ""))
    if status_code and status_code != "0":
        raise SystemExit(f"restore returned device statusCode={status_code}")

    readback = client.get_algorithm_store_cfg()
    assert_request_ok("RESTORE_VERIFY_READ_FAILED", readback)
    readback_summary = summarize_algorithm_store(
        parse_algorithm_store_xml(readback.get("text", "")),
    )
    print_json(
        "RESTORE_RESULT",
        {
            "ok": True,
            "backup": str(path),
            "expected_algorithm_type": child_text(backup_root, "AlgorithmType"),
            "readback": readback_summary,
        },
    )


def main() -> None:
    args = parse_args()
    load_env_file(Path(args.env_file))
    config = P6SConfig.from_env()
    client = P6SCameraClient(config)

    print_json("CAMERA", config.safe_summary())
    if not config.configured():
        raise SystemExit("P6S camera connection config is incomplete")

    if args.restore:
        restore_xml(client, args.restore)
        return

    result = client.get_algorithm_store_cfg()
    assert_request_ok("READ_ALGORITHM_STORE_FAILED", result)
    xml_text = result.get("text", "")
    before_root = parse_algorithm_store_xml(xml_text)
    before = summarize_algorithm_store(before_root)
    print_json("ALGORITHM_STORE_BEFORE", before)

    patched_xml, changed, patch_before, patch_after, mismatches = build_patch(
        xml_text,
        args.target,
    )
    if args.print_diff_summary or args.apply:
        print_json(
            "PATCH_DIFF_SUMMARY",
            {
                "target": args.target,
                "changed_fields": ["AlgorithmType"] if changed else [],
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

    backup_path = backup_xml(xml_text)
    print_json("BACKUP", {"path": str(backup_path)})
    write_result = client.set_algorithm_store_cfg(patched_xml)
    assert_request_ok("WRITE_ALGORITHM_STORE_FAILED", write_result)
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

    after_result = client.get_algorithm_store_cfg()
    assert_request_ok("VERIFY_ALGORITHM_STORE_FAILED", after_result)
    after = summarize_algorithm_store(
        parse_algorithm_store_xml(after_result.get("text", "")),
    )
    print_json("ALGORITHM_STORE_AFTER", after)

    if after.get("algorithm_type") != args.target:
        raise SystemExit(f"AlgorithmType did not persist as {args.target}")

    subconfig_summary = read_subconfig_summaries(client)
    print_json("SUBCONFIG_SUMMARY_AFTER", subconfig_summary)
    assert_key_subconfigs_enabled(subconfig_summary)


if __name__ == "__main__":
    main()
