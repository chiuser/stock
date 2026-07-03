"""Validate the local P6S event flow with fixture payloads."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import feishu, image_links, p6s_events
from app.services.event_store import RequestMeta

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


@contextmanager
def patched_env(values: dict[str, str]):
    previous = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


async def validate() -> None:
    role_env = {
        "P6S_FACE_GROUP_MEMBERS_ID": "c1e42a1f2531467bae464da8a79dad53",
        "P6S_FACE_GROUP_MEMBERS_NAME": "会员",
        "P6S_FACE_GROUP_COACHES_ID": "9c89bc7bc2234801b5ae0f8d60da8c30",
        "P6S_FACE_GROUP_COACHES_NAME": "教练",
        "P6S_FACE_GROUP_STAFF_ID": "4dcafc2c9fbd4d1fa267ccbf145c8861",
        "P6S_FACE_GROUP_STAFF_NAME": "员工",
        "ATTENDANCE_DB_ENABLED": "false",
    }
    with patched_env(role_env), tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        request_meta = RequestMeta(
            client_host="127.0.0.1",
            content_type="application/json",
            user_agent="fixture-validator",
            method="POST",
            path="/api/p6s/events/test-secret",
        )

        known = load_fixture("p6s_face_reco_known.json")
        known_result = await p6s_events.handle_event(
            known,
            request_meta=request_meta,
            root=root,
            notify=False,
        )
        assert known_result.result == "known"
        assert known_result.ack["operator"] == "FaceReco-Ack"
        assert known_result.ack["info"]["uniqueId"] == "3427976339944670"

        for fixture, role, role_name, title in (
            ("p6s_face_reco_member.json", "members", "会员", "会员入场提醒"),
            ("p6s_face_reco_coach.json", "coaches", "教练", "教练入场提醒"),
            ("p6s_face_reco_staff.json", "staff", "员工", "员工入场提醒"),
            ("p6s_face_reco_unknown_role.json", "unknown", "未知身份", "人员入场提醒"),
        ):
            result = await p6s_events.handle_event(
                load_fixture(fixture),
                request_meta=request_meta,
                root=root,
                notify=False,
            )
            assert result.result == "known"
            assert result.record_file is not None
            record = json.loads(result.record_file.path.read_text(encoding="utf-8"))
            matched = record["matched_person"]
            assert matched["person_role"] == role
            assert matched["person_role_name"] == role_name
            assert matched["notification_title"] == title

        duplicate_result = await p6s_events.handle_event(
            known,
            request_meta=request_meta,
            root=root,
            notify=False,
        )
        assert duplicate_result.result == "duplicate"
        assert duplicate_result.duplicate is True

        stranger = load_fixture("p6s_face_reco_stranger.json")
        stranger_result = await p6s_events.handle_event(
            stranger,
            request_meta=request_meta,
            root=root,
            notify=False,
        )
        assert stranger_result.result == "stranger"
        assert stranger_result.image is not None
        assert stranger_result.link is not None
        assert stranger_result.record_file is not None
        record_text = stranger_result.record_file.path.read_text(encoding="utf-8")
        assert stranger_result.link.token not in record_text

        missing_image = load_fixture("p6s_face_reco_missing_image.json")
        missing_result = await p6s_events.handle_event(
            missing_image,
            request_meta=request_meta,
            root=root,
            notify=False,
        )
        assert missing_result.result == "stranger"
        assert missing_result.image is None

        heartbeat = load_fixture("p6s_heartbeat.json")
        heartbeat_result = await p6s_events.handle_event(
            heartbeat,
            request_meta=request_meta,
            root=root,
            notify=False,
        )
        assert heartbeat_result.result == "heartbeat"
        assert heartbeat_result.ack["operator"] == "heartbeat-Ack"

        validate_feishu_payloads()
        validate_image_routes(root)
        validate_cleanup_script()

    print("P6S event flow fixtures validated")


def validate_feishu_payloads() -> None:
    known_payload = feishu.build_known_face_post(
        name="苏苏",
        person_id="3785841386866689",
        device_sn="SN-FIXTURE-001",
        event_time="2026-07-02 10:10:00",
        event_id="member-001",
        role_name="会员",
        title="会员入场提醒",
    )
    assert _post_title(known_payload) == "会员入场提醒"
    assert any(
        item.get("text") == "身份类型: 会员"
        for line in _post_lines(known_payload)
        for item in line
    )

    unknown_payload = feishu.build_unknown_face_post(
        image_path=None,
        device_sn="SN-FIXTURE-001",
        event_time="2026-07-02 10:05:00",
        event_id="stranger-001",
        storage_path="/var/lib/camera-face-guard/p6s_events/strangers/2026-07-02/a.jpg",
        view_url="http://example.test/api/p6s/event-images/view/token",
    )
    assert _post_title(unknown_payload) == "发现陌生人入场"
    assert any(
        item.get("tag") == "a" and item.get("text") == "查看图片"
        for line in _post_lines(unknown_payload)
        for item in line
    )


def validate_image_routes(root: Path) -> None:
    with patched_env(
        {
            "P6S_EVENT_IMAGE_DIR": str(root),
            "CAMERA_SESSION_SECRET": "fixture-session-secret",
            "CAMERA_ADMIN_PASSWORD": "fixture-admin-password",
        }
    ):
        from app.routers import camera
        from app.routers.auth import require_admin

        image_dir = root / "strangers" / "2026-07-02"
        image_dir.mkdir(parents=True, exist_ok=True)
        image_path = image_dir / "fixture.jpg"
        image_path.write_bytes(b"\xff\xd8\xfffixture")
        legacy_path = root / "legacy.jpg"
        legacy_path.write_bytes(b"\xff\xd8\xfflegacy")
        link = image_links.create_image_link(
            record_dedupe_key="fixture-link",
            relative_path="strangers/2026-07-02/fixture.jpg",
            content_type="image/jpeg",
            root=root,
        )

        resolved = image_links.resolve_image_link(link.token, root=root)
        assert resolved.image_path == image_path
        assert resolved.content_type == "image/jpeg"

        legacy_route = next(
            route
            for route in camera.router.routes
            if getattr(route, "path", "") == "/p6s/event-images/{filename}"
        )
        assert any(
            dependency.call is require_admin
            for dependency in legacy_route.dependant.dependencies
        )


def validate_cleanup_script() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        old_file = root / "raw" / "2026-06-01" / "old.json"
        new_file = root / "raw" / "2026-07-02" / "new.json"
        link_file = root / "links" / "2026-06-01" / "old-link.json"
        old_file.parent.mkdir(parents=True)
        new_file.parent.mkdir(parents=True)
        link_file.parent.mkdir(parents=True)
        old_file.write_text("old", encoding="utf-8")
        new_file.write_text("new", encoding="utf-8")
        link_file.write_text("old-link", encoding="utf-8")

        cleanup_script = PROJECT_ROOT / "scripts" / "cleanup_p6s_event_store.py"
        dry_run = subprocess.run(
            [
                sys.executable,
                str(cleanup_script),
                "--root",
                str(root),
                "--days",
                "30",
                "--today",
                "2026-07-03",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        dry_report = json.loads(dry_run.stdout)
        assert dry_report["apply"] is False
        assert dry_report["target_count"] == 2
        assert old_file.exists()

        apply_run = subprocess.run(
            [
                sys.executable,
                str(cleanup_script),
                "--root",
                str(root),
                "--days",
                "30",
                "--today",
                "2026-07-03",
                "--apply",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        apply_report = json.loads(apply_run.stdout)
        assert apply_report["apply"] is True
        assert apply_report["target_count"] == 2
        assert not old_file.exists()
        assert not link_file.exists()
        assert new_file.exists()


def _post_title(payload: dict) -> str:
    return payload["content"]["post"]["zh_cn"]["title"]


def _post_lines(payload: dict) -> list[list[dict[str, str]]]:
    return payload["content"]["post"]["zh_cn"]["content"]


if __name__ == "__main__":
    asyncio.run(validate())
