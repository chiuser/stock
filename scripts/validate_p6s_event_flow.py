"""Validate the local P6S event flow with fixture payloads."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import face_gallery, face_recheck, feishu, image_links, p6s_events, recognition_monitor
from app.services.event_store import RequestMeta

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


def with_capture_image(payload: dict) -> dict:
    payload_copy = copy.deepcopy(payload)
    image_source = load_fixture("p6s_face_reco_stranger.json")["info"]["CaptureImage"]
    payload_copy.setdefault("info", {})["CaptureImage"] = image_source
    return payload_copy


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
        "FACE_RECHECK_ENABLED": "false",
        "FACE_RECHECK_MODE": "shadow",
        "FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_URL": "",
        "FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_SECRET": "",
        "FEISHU_WEBHOOK_URL": "",
        "FEISHU_WEBHOOK_SECRET": "",
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

        known = with_capture_image(load_fixture("p6s_face_reco_known.json"))
        known_result = await p6s_events.handle_event(
            known,
            request_meta=request_meta,
            root=root,
            notify=False,
        )
        assert known_result.result == "known"
        assert known_result.ack["operator"] == "FaceReco-Ack"
        assert known_result.ack["info"]["uniqueId"] == "3427976339944670"
        assert known_result.image is not None
        assert known_result.link is not None
        assert "/faces/" in str(known_result.image.path)
        assert known_result.record_file is not None
        known_record_text = known_result.record_file.path.read_text(encoding="utf-8")
        known_record = json.loads(known_record_text)
        assert known_record["image"]["status"] == "saved"
        assert known_record["link"] is not None
        assert known_result.link.token not in known_record_text
        known_monitor_row = recognition_monitor.build_event_row(
            known_record,
            record_path=known_result.record_file.path,
            root=root,
        )
        assert known_monitor_row["event_dedupe_key"] == known_record["dedupe_key"]
        assert known_monitor_row["camera_result"] == "known"
        assert known_monitor_row["camera_person_name"] == "小明"
        assert known_monitor_row["camera_person_id"] == "3427976339944670"
        assert known_monitor_row["record_relative_path"].startswith("records/2026-07-02/")

        dual = load_fixture("p6s_face_reco_dual_image.json")
        dual_result = await p6s_events.handle_event(
            dual,
            request_meta=request_meta,
            root=root,
            notify=False,
        )
        assert dual_result.result == "known"
        assert dual_result.image is not None
        assert dual_result.link is not None
        assert dual_result.record_file is not None
        dual_record_text = dual_result.record_file.path.read_text(encoding="utf-8")
        dual_record = json.loads(dual_record_text)
        assert dual_record["image"]["kind"] == "background"
        assert dual_record["image"]["source"] == "BackgroundImage"
        assert "_background_" in dual_record["image"]["storage_path"]
        assert dual_record["images"]["background"]["status"] == "saved"
        assert dual_record["images"]["capture"]["status"] == "saved"
        assert "_capture_" in dual_record["images"]["capture"]["storage_path"]
        assert dual_record["links"]["background"]["relative_path"] == dual_record["images"]["background"]["relative_path"]
        assert dual_record["links"]["capture"]["relative_path"] == dual_record["images"]["capture"]["relative_path"]
        assert "token_hash" in dual_record["links"]["background"]
        assert "token_hash" in dual_record["links"]["capture"]
        assert dual_result.link.token not in dual_record_text
        dual_monitor_row = recognition_monitor.build_event_row(
            dual_record,
            record_path=dual_result.record_file.path,
            root=root,
        )
        assert dual_monitor_row["background_relative_path"] == dual_record["images"]["background"]["relative_path"]
        assert dual_monitor_row["capture_relative_path"] == dual_record["images"]["capture"]["relative_path"]

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
            if role == "staff":
                assert matched["camera_person_id"] == "3427976339944670"

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
        validate_face_gallery_matching()
        await validate_face_recheck_shadow_flow(request_meta)
        validate_recognition_monitor_backfill(root)
        validate_recognition_monitor_api_helpers(root, known_monitor_row)
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
        storage_path="/var/lib/camera-face-guard/p6s_events/faces/2026-07-02/member.jpg",
        background_view_url="http://example.test/api/p6s/event-images/view/member-background-token",
        capture_view_url="http://example.test/api/p6s/event-images/view/member-capture-token",
    )
    assert _post_title(known_payload) == "会员入场提醒"
    assert any(
        item.get("text") == "身份类型: 会员"
        for line in _post_lines(known_payload)
        for item in line
    )
    assert any(
        item.get("tag") == "a" and item.get("text") == "查看背景全图"
        for line in _post_lines(known_payload)
        for item in line
    )
    assert any(
        item.get("tag") == "a" and item.get("text") == "查看人脸图"
        for line in _post_lines(known_payload)
        for item in line
    )

    unknown_payload = feishu.build_unknown_face_post(
        image_path=None,
        device_sn="SN-FIXTURE-001",
        event_time="2026-07-02 10:05:00",
        event_id="stranger-001",
        storage_path="/var/lib/camera-face-guard/p6s_events/strangers/2026-07-02/a.jpg",
        background_view_url="http://example.test/api/p6s/event-images/view/stranger-background-token",
        capture_view_url="http://example.test/api/p6s/event-images/view/stranger-capture-token",
    )
    assert _post_title(unknown_payload) == "发现陌生人入场"
    assert any(
        item.get("tag") == "a" and item.get("text") == "查看背景全图"
        for line in _post_lines(unknown_payload)
        for item in line
    )
    assert any(
        item.get("tag") == "a" and item.get("text") == "查看人脸图"
        for line in _post_lines(unknown_payload)
        for item in line
    )

    shadow_payload = feishu.build_face_recheck_shadow_post(
        device_sn="SN-FIXTURE-001",
        event_time="2026-07-02 10:05:00",
        event_id="shadow-001",
        camera_result="stranger",
        camera_person_summary=None,
        recheck_result=_mock_recheck_result().to_dict(),
        background_view_url="http://example.test/api/p6s/event-images/view/shadow-background-token",
        capture_view_url="http://example.test/api/p6s/event-images/view/shadow-capture-token",
    )
    assert _post_title(shadow_payload) == "InsightFace Shadow 对比"
    assert any(
        item.get("text") == "摄像头结果: stranger"
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text") == "InsightFace 状态: passed"
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text") == "是否检测到人脸: 是"
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text") == "检测分阈值: >= 0.65"
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text") == "Gallery 是否通过: True"
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text", "").startswith("Gallery 候选集: 1. 小明")
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text") == "结果对齐: camera_unknown"
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("tag") == "a" and item.get("text") == "查看背景全图"
        for line in _post_lines(shadow_payload)
        for item in line
    )


def validate_face_gallery_matching() -> None:
    import numpy as np

    records = [
        {
            "person_id": "3427976339944670",
            "credential_no": "3427976339944670",
            "credential_type": "2",
            "name": "小明",
            "sex": "0",
            "person_type": "staff",
            "group_id": "4dcafc2c9fbd4d1fa267ccbf145c8861",
            "group_name": "员工",
            "source_filename": "I小明#S0#T2#M3427976339944670.jpg",
            "source_image_path": "/private/fixture/I小明#S0#T2#M3427976339944670.jpg",
            "quality_flags": [],
        },
        {
            "person_id": "3785841386866689",
            "credential_no": "3785841386866689",
            "credential_type": "2",
            "name": "苏苏",
            "sex": "0",
            "person_type": "member",
            "group_id": "c1e42a1f2531467bae464da8a79dad53",
            "group_name": "会员",
            "source_filename": "I苏苏#S0#T2#M3785841386866689.jpg",
            "source_image_path": "/private/fixture/I苏苏#S0#T2#M3785841386866689.jpg",
            "quality_flags": [],
        },
    ]
    index = face_gallery.FaceGalleryIndex(
        embeddings=np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        records=records,
        manifest={"records": records},
    )
    match = index.match(
        np.array([1.0, 0.0], dtype=np.float32),
        similarity_threshold=0.5,
        similarity_margin=0.03,
        camera_person={"name": "小明", "person_id": "3427976339944670"},
    )
    assert match is not None
    assert match.accepted is True
    assert match.person_type == "staff"
    assert match.camera_identity_status == "name_and_id_matched"
    assert len(match.candidates) == 2
    assert match.candidates[0].name == "小明"

    conflict = index.match(
        np.array([1.0, 0.0], dtype=np.float32),
        similarity_threshold=0.5,
        similarity_margin=0.03,
        camera_person={"name": "其他人", "person_id": "000"},
    )
    assert conflict is not None
    assert conflict.camera_identity_status == "identity_conflict"

    low_confidence = index.match(
        np.array([0.51, 0.49], dtype=np.float32),
        similarity_threshold=0.8,
        similarity_margin=0.03,
        camera_person=None,
    )
    assert low_confidence is not None
    assert low_confidence.accepted is False
    assert low_confidence.camera_identity_status == "camera_unknown"


async def validate_face_recheck_shadow_flow(request_meta: RequestMeta) -> None:
    env = {
        "ATTENDANCE_DB_ENABLED": "false",
        "FACE_RECHECK_ENABLED": "true",
        "FACE_RECHECK_MODE": "shadow",
        "FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_URL": "",
        "FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_SECRET": "",
        "FEISHU_WEBHOOK_URL": "",
        "FEISHU_WEBHOOK_SECRET": "",
    }
    with patched_env(env), tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(
            p6s_events.face_recheck,
            "run_face_recheck",
            return_value=_mock_recheck_result(),
        ):
            result = await p6s_events.handle_event(
                with_capture_image(load_fixture("p6s_face_reco_known.json")),
                request_meta=request_meta,
                root=Path(temp_dir),
                notify=True,
            )
            assert result.result == "known"
            assert result.record_file is not None
            record_text = result.record_file.path.read_text(encoding="utf-8")
            record = json.loads(record_text)
    assert record["face_recheck"]["enabled"] is True
    assert record["face_recheck"]["mode"] == "shadow"
    assert record["face_recheck"]["status"] == "passed"
    assert record["face_recheck"]["decision"] == "allow_original"
    assert record["face_recheck_shadow_feishu"]["skipped"] is True
    assert "shadow-background-token" not in record_text


def _mock_recheck_result() -> face_recheck.FaceRecheckResult:
    return face_recheck.FaceRecheckResult(
        enabled=True,
        mode="shadow",
        status="passed",
        decision="allow_original",
        reason="quality_passed",
        image_source="background",
        face_count=1,
        selected_face=face_recheck.DetectedFaceSummary(
            index=0,
            bbox=(1.0, 2.0, 101.0, 122.0),
            det_score=0.91,
            width=100.0,
            height=120.0,
            blur_score=132.4,
            frontal_score=0.12,
            quality_flags=[],
        ),
        gallery_match=face_recheck.GalleryMatch(
            person_id="3427976339944670",
            credential_no="3427976339944670",
            credential_type="2",
            name="小明",
            sex="0",
            person_type="staff",
            group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
            group_name="员工",
            similarity=0.91,
            second_similarity=0.42,
            accepted=True,
            camera_identity_status="camera_unknown",
            candidates=[
                face_recheck.GalleryCandidate(
                    rank=1,
                    person_id="3427976339944670",
                    credential_no="3427976339944670",
                    credential_type="2",
                    name="小明",
                    sex="0",
                    person_type="staff",
                    group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                    group_name="员工",
                    similarity=0.91,
                ),
                face_recheck.GalleryCandidate(
                    rank=2,
                    person_id="3785841386866689",
                    credential_no="3785841386866689",
                    credential_type="2",
                    name="苏苏",
                    sex="0",
                    person_type="member",
                    group_id="c1e42a1f2531467bae464da8a79dad53",
                    group_name="会员",
                    similarity=0.42,
                ),
            ],
        ),
        elapsed_ms=12,
        thresholds=face_recheck.FaceRecheckThresholds(
            det_score_threshold=0.65,
            min_face_width=80,
            min_face_height=80,
            blur_threshold=80.0,
            frontal_max_yaw_score=0.35,
            similarity_threshold=0.5,
            similarity_margin=0.03,
        ),
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


def validate_recognition_monitor_backfill(root: Path) -> None:
    backfill_script = PROJECT_ROOT / "scripts" / "backfill_recognition_events.py"
    dry_run = subprocess.run(
        [
            sys.executable,
            str(backfill_script),
            "--root",
            str(root),
            "--date",
            "2026-07-02",
            "--limit",
            "3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(dry_run.stdout)
    assert report["apply"] is False
    assert report["face_reco"] == 3
    assert report["prepared"] == 3
    assert report["upserted"] == 0
    assert report["parse_error_count"] == 0


def validate_recognition_monitor_api_helpers(root: Path, monitor_row: dict) -> None:
    event_dto = recognition_monitor.row_to_event(monitor_row, include_detail=True)
    assert event_dto["event_key"] == monitor_row["event_dedupe_key"]
    assert event_dto["camera"]["name"] == "小明"
    assert event_dto["images"]["capture"]["api_url"].startswith("/api/recognition-monitor/images?")
    assert "storage_path" not in json.dumps(event_dto, ensure_ascii=False)

    capture_relative_path = monitor_row["capture_relative_path"]
    image_path, content_type = recognition_monitor.resolve_image_path(capture_relative_path, root=root)
    assert image_path.exists()
    assert content_type == "image/jpeg"
    for bad_path in ("/tmp/a.jpg", "../faces/a.jpg", "raw/2026-07-02/a.json"):
        try:
            recognition_monitor.resolve_image_path(bad_path, root=root)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe path unexpectedly allowed: {bad_path}")

    invalid_crop = recognition_monitor.ensure_insightface_crop(
        {
            "dedupe_key": "fixture-crop",
            "operator": "FaceReco",
            "event_id": "fixture-crop",
            "event_time": "2026-07-02 10:00:00",
            "received_at": "2026-07-02T10:00:00+08:00",
            "camera_serial_number": "SN-FIXTURE-001",
            "images": {"background": {"relative_path": capture_relative_path}},
            "face_recheck": {
                "selected_face": {"bbox": [1, 1, 20, 20]},
            },
        },
        root=root,
    )
    assert invalid_crop["status"] in {"crop_failed", "saved"}

    from app.routers import recognition_monitor as recognition_router
    from app.routers.auth import require_admin

    protected_paths = {
        "/recognition-monitor/summary",
        "/recognition-monitor/events",
        "/recognition-monitor/events/{event_key}",
        "/recognition-monitor/images",
    }
    routes_by_path = {
        getattr(route, "path", ""): route
        for route in recognition_router.router.routes
    }
    for path in protected_paths:
        route = routes_by_path[path]
        assert any(
            dependency.call is require_admin
            for dependency in route.dependant.dependencies
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
