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
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import face_gallery, face_recheck, feishu, image_links, p6s_events, recognition_monitor
from app.services.event_store import EventIdentity, RequestMeta

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
            ("p6s_face_reco_member.json", "members", "会员", "😊 会员入场提醒"),
            ("p6s_face_reco_coach.json", "coaches", "教练", "🧑‍🏫 教练入场提醒"),
            ("p6s_face_reco_staff.json", "staff", "员工", "🧑‍💼 员工入场提醒"),
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
        validate_face_recheck_fallback_order()
        await validate_face_recheck_shadow_flow(request_meta)
        await validate_final_decision_flow(request_meta)
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
        title="😊 会员入场提醒",
        storage_path="/var/lib/camera-face-guard/p6s_events/faces/2026-07-02/member.jpg",
        background_view_url="http://example.test/api/p6s/event-images/view/member-background-token",
        capture_view_url="http://example.test/api/p6s/event-images/view/member-capture-token",
    )
    assert _post_title(known_payload) == "😊 会员入场提醒"
    known_text = "\n".join(_post_plain_texts(known_payload))
    assert "姓名: 苏苏" in known_text
    assert "身份类型: 会员" in known_text
    assert "时间: 2026-07-02 10:10:00" in known_text
    assert "事件 ID: member-001" in known_text
    assert "人员 ID:" not in known_text
    assert "设备:" not in known_text
    assert "保存位置:" not in known_text
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
    assert _post_title(unknown_payload) == "‼️ 发现陌生人入场"
    unknown_text = "\n".join(_post_plain_texts(unknown_payload))
    assert "时间: 2026-07-02 10:05:00" in unknown_text
    assert "事件 ID: stranger-001" in unknown_text
    assert "人员 ID:" not in unknown_text
    assert "设备:" not in unknown_text
    assert "保存位置:" not in unknown_text
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
        final_decision={
            "mode": "verify_and_override",
            "action": "trigger",
            "reason": "valid_face_decision",
            "primary_trigger": {
                "kind": "known",
                "face_key": "background:0",
                "image_source": "background",
                "face_index": 0,
                "reason": "gallery_high_confidence_match",
                "person_type": "staff",
                "person_id": "3427976339944670",
                "name": "小明",
                "group_name": "员工",
                "similarity": 0.91,
            },
            "extra_triggers": [],
            "suppressed_faces": [],
        },
        background_view_url="http://example.test/api/p6s/event-images/view/shadow-background-token",
        capture_view_url="http://example.test/api/p6s/event-images/view/shadow-capture-token",
    )
    assert _post_title(shadow_payload) == "InsightFace Shadow 对比"
    shadow_text = "\n".join(_post_plain_texts(shadow_payload))
    assert "【最终结论】" in shadow_text
    assert "最终判断: 触发熟人通知" in shadow_text
    assert "采信来源: InsightFace" in shadow_text
    assert "主触发: 小明 / 员工 / 3427976339944670 / background:0 / 相似度 0.91" in shadow_text
    assert "【InsightFace 总览】" in shadow_text
    assert "【逐脸结果】" in shadow_text
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
        item.get("text", "").startswith("关键阈值: 检测>= 0.65")
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text") == "Gallery 是否通过: True"
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text", "").startswith("主脸候选 #1: 小明 / 员工 / 3427976339944670 / 相似度 0.91")
        for line in _post_lines(shadow_payload)
        for item in line
    )
    assert any(
        item.get("text", "").startswith("人脸 1 候选 #2: 苏苏 / 会员 / 3785841386866689 / 相似度 0.42")
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
        camera_match_similarity_threshold=0.3,
        camera_match_gap_threshold=0.03,
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
        camera_match_similarity_threshold=0.3,
        camera_match_gap_threshold=0.03,
        similarity_margin=0.03,
        camera_person={"name": "其他人", "person_id": "000"},
    )
    assert conflict is not None
    assert conflict.camera_identity_status == "identity_conflict"

    low_confidence = index.match(
        np.array([0.51, 0.49], dtype=np.float32),
        similarity_threshold=0.8,
        camera_match_similarity_threshold=0.3,
        camera_match_gap_threshold=0.03,
        similarity_margin=0.03,
        camera_person=None,
    )
    assert low_confidence is not None
    assert low_confidence.accepted is False
    assert low_confidence.camera_identity_status == "camera_unknown"

    low_camera_match_index = face_gallery.FaceGalleryIndex(
        embeddings=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        records=records,
        manifest={"records": records},
    )
    low_camera_match = low_camera_match_index.match(
        np.array([0.31, 0.10, 0.9454626], dtype=np.float32),
        similarity_threshold=0.35,
        camera_match_similarity_threshold=0.30,
        camera_match_gap_threshold=0.03,
        similarity_margin=0.0,
        camera_person={"name": "小明", "person_id": "3427976339944670"},
    )
    assert low_camera_match is not None
    assert low_camera_match.camera_identity_status == "name_and_id_matched"
    assert low_camera_match.accepted is True
    assert low_camera_match.accepted_threshold == 0.30

    low_conflict = low_camera_match_index.match(
        np.array([0.31, 0.10, 0.9454626], dtype=np.float32),
        similarity_threshold=0.35,
        camera_match_similarity_threshold=0.30,
        camera_match_gap_threshold=0.03,
        similarity_margin=0.0,
        camera_person={"name": "其他人", "person_id": "000"},
    )
    assert low_conflict is not None
    assert low_conflict.camera_identity_status == "identity_conflict"
    assert low_conflict.accepted is False
    assert low_conflict.accepted_threshold == 0.35

    near_tie_camera_match = index.match(
        np.array([0.49, 0.51], dtype=np.float32),
        similarity_threshold=0.35,
        camera_match_similarity_threshold=0.30,
        camera_match_gap_threshold=0.03,
        similarity_margin=0.0,
        camera_person={"name": "小明", "person_id": "3427976339944670"},
    )
    assert near_tie_camera_match is not None
    assert near_tie_camera_match.name == "小明"
    assert near_tie_camera_match.camera_identity_status == "name_and_id_matched"
    assert near_tie_camera_match.accepted is True
    assert near_tie_camera_match.candidates[0].name == "苏苏"


def validate_face_recheck_fallback_order() -> None:
    settings = _fallback_settings()
    background_path = Path("/tmp/p6s-background.jpg")
    capture_path = Path("/tmp/p6s-capture.jpg")
    recheck_input = _fallback_input(background_path, capture_path)

    attempts = face_recheck._image_attempts(recheck_input)  # noqa: SLF001
    assert attempts == [(background_path, "background"), (capture_path, "capture")]

    capture_passed = _fallback_face(
        reason="quality_passed",
        image_source="capture",
        face_index=0,
        similarity=0.51,
        status="passed",
    )
    with patch.object(
        face_recheck,
        "_analyze_image_faces",
        side_effect=[[], [capture_passed]],
    ) as analyze_faces:
        result = face_recheck.run_face_recheck(recheck_input, settings=settings)
    assert result.image_source == "capture"
    assert analyze_faces.call_count == 2
    assert analyze_faces.call_args_list[0].kwargs["image_source"] == "background"
    assert analyze_faces.call_args_list[1].kwargs["image_source"] == "capture"

    background_low_similarity = _fallback_face(
        reason="quality_passed",
        image_source="background",
        face_index=0,
        similarity=0.34,
        status="passed",
    )
    with patch.object(
        face_recheck,
        "_analyze_image_faces",
        side_effect=[[background_low_similarity], [capture_passed]],
    ) as analyze_faces:
        result = face_recheck.run_face_recheck(recheck_input, settings=settings)
    assert result.image_source == "capture"
    assert analyze_faces.call_count == 2

    background_ok_similarity = _fallback_face(
        reason="quality_passed",
        image_source="background",
        face_index=0,
        similarity=0.35,
        status="passed",
    )
    with patch.object(
        face_recheck,
        "_analyze_image_faces",
        return_value=[background_ok_similarity],
    ) as analyze_faces:
        result = face_recheck.run_face_recheck(recheck_input, settings=settings)
    assert result.image_source == "background"
    assert analyze_faces.call_count == 1

    background_multi_face_left = _fallback_face(
        reason="multiple_faces",
        image_source="background",
        face_index=0,
        similarity=0.20,
        status="filtered",
    )
    background_multi_face_right = _fallback_face(
        reason="multiple_faces",
        image_source="background",
        face_index=1,
        similarity=0.30,
        status="filtered",
    )
    with patch.object(
        face_recheck,
        "_analyze_image_faces",
        side_effect=[[background_multi_face_left, background_multi_face_right], [capture_passed]],
    ) as analyze_faces:
        result = face_recheck.run_face_recheck(recheck_input, settings=settings)
    assert result.face_count == 2
    assert len(result.faces) == 3
    assert analyze_faces.call_count == 2


def _fallback_settings() -> face_recheck.FaceRecheckSettings:
    return face_recheck.FaceRecheckSettings(
        enabled=True,
        mode=face_recheck.FaceRecheckMode.SHADOW,
        model_name="buffalo_l",
        model_root="/tmp/insightface",
        provider="CPUExecutionProvider",
        det_score_threshold=0.55,
        min_face_width=45,
        min_face_height=60,
        blur_threshold=80.0,
        frontal_max_yaw_score=0.35,
        head_pitch_min=-45.0,
        similarity_threshold=0.35,
        camera_match_similarity_threshold=0.30,
        camera_match_gap_threshold=0.03,
        camera_match_rescue_min_face_width=40,
        camera_match_rescue_min_face_height=50,
        known_extra_unknown_min_face_width=80,
        known_extra_unknown_min_face_height=80,
        border_margin_ratio=0.02,
        motion_blur_threshold=None,
        low_identity_similarity=0.28,
        low_identity_gap=0.04,
        similarity_margin=0.0,
        gallery_path="/tmp/gallery.npz",
        gallery_manifest_path="/tmp/gallery_manifest.json",
        fail_open=True,
        timeout_seconds=3,
    )


def _fallback_input(
    background_path: Path,
    capture_path: Path | None,
) -> face_recheck.FaceRecheckInput:
    return face_recheck.FaceRecheckInput(
        identity=EventIdentity(
            dedupe_key="fallback-fixture",
            operator="FaceReco",
            serial_number="SN-FIXTURE-001",
            event_id="fallback-fixture",
            picture_md5="",
            event_time="2026-07-05 08:12:14",
            event_time_compact="20260705081214",
            received_at=datetime(2026, 7, 5, 8, 12, 14),
            event_day="2026-07-05",
        ),
        route_result="known",
        camera_person={"name": "菊", "person_id": "fixture-person"},
        primary_image_path=capture_path,
        background_image_path=background_path,
        capture_image_path=capture_path,
        background_view_url=None,
        capture_view_url=None,
    )


def _fallback_face(
    *,
    reason: str,
    image_source: str,
    face_index: int,
    similarity: float | None = None,
    status: str = "filtered",
) -> face_recheck.FaceRecheckFaceResult:
    return face_recheck.FaceRecheckFaceResult(
        image_source=image_source,  # type: ignore[arg-type]
        face_index=face_index,
        face_key=f"{image_source}:{face_index}",
        selected_face=face_recheck.DetectedFaceSummary(
            index=face_index,
            bbox=(10.0 + face_index, 20.0, 110.0 + face_index, 140.0),
            det_score=0.91,
            width=100.0,
            height=120.0,
            blur_score=100.0,
            border_margin_ratio=0.2,
            motion_blur_score=12.0,
            frontal_score=0.1,
            head_pitch=None,
            quality_flags=[] if status == "passed" else [reason],
        ),
        status=status,  # type: ignore[arg-type]
        reason=reason,
        gallery_match=_fallback_gallery_match(similarity) if similarity is not None else None,
    )


def _fallback_gallery_match(similarity: float) -> face_recheck.GalleryMatch:
    return face_recheck.GalleryMatch(
        person_id="fixture-person",
        credential_no="fixture-person",
        credential_type="2",
        name="菊",
        sex="0",
        person_type="member",
        group_id="c1e42a1f2531467bae464da8a79dad53",
        group_name="会员",
        similarity=similarity,
        second_similarity=None,
        accepted=similarity >= 0.35,
        accepted_threshold=0.35,
        camera_identity_status="name_matched",
    )


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
    assert record["face_recheck"]["faces"][0]["face_key"] == "background:0"
    assert record["face_recheck"]["faces"][0]["crop"]["status"] in {"saved", "error"}
    assert record["face_recheck_shadow_feishu"]["skipped"] is True
    assert "shadow-background-token" not in record_text
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert len(face_rows) == 1
    assert face_rows[0]["face_key"] == "background:0"
    assert face_rows[0]["gallery_name"] == "小明"


async def validate_final_decision_flow(request_meta: RequestMeta) -> None:
    env = {
        "ATTENDANCE_DB_ENABLED": "false",
        "FACE_RECHECK_ENABLED": "true",
        "FACE_RECHECK_MODE": "verify_and_override",
        "FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_URL": "",
        "FACE_RECHECK_SHADOW_FEISHU_WEBHOOK_SECRET": "",
        "FEISHU_WEBHOOK_URL": "",
        "FEISHU_WEBHOOK_SECRET": "",
    }
    with patched_env(
        {
            "FACE_RECHECK_ENABLED": "true",
            "FACE_RECHECK_MODE": "verify_and_override",
            "FACE_RECHECK_MOTION_BLUR_THRESHOLD": "",
        }
    ):
        settings = face_recheck.FaceRecheckSettings.from_env()
    assert settings.border_margin_ratio == 0.02
    assert settings.motion_blur_threshold is None
    assert settings.low_identity_similarity == 0.28
    assert settings.low_identity_gap == 0.04

    async def run_case(payload: dict, result: face_recheck.FaceRecheckResult) -> tuple[p6s_events.EventHandleResult, dict]:
        with patched_env(env), tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(p6s_events.face_recheck, "run_face_recheck", return_value=result):
                handled = await p6s_events.handle_event(
                    with_capture_image(payload),
                    request_meta=request_meta,
                    root=Path(temp_dir),
                    notify=False,
                )
            assert handled.record_file is not None
            record = json.loads(handled.record_file.path.read_text(encoding="utf-8"))
            return handled, record

    known_payload = load_fixture("p6s_face_reco_known.json")
    stranger_payload = load_fixture("p6s_face_reco_stranger.json")
    disabled_decision = face_recheck.build_final_recognition_decision(
        camera_result="known",
        camera_person={"name": "小明", "person_id": "3427976339944670"},
        recheck_result=replace(
            _result_for_faces([], mode="verify_and_override"),
            enabled=False,
            status="skipped",
            reason="disabled",
        ),
    )
    assert disabled_decision.action == "allow_original"

    same_person = _result_for_faces(
        [
            _known_face(
                name="小明",
                person_id="3427976339944670",
                person_type="staff",
                group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                group_name="员工",
                camera_identity_status="name_and_id_matched",
            )
        ]
    )
    handled, record = await run_case(known_payload, same_person)
    assert handled.result == "known"
    assert record["result"] == "known"
    assert record["camera_result"] == "known"
    assert record["final_recognition_decision"]["action"] == "trigger"
    assert record["final_recognition_decision"]["primary_trigger"]["name"] == "小明"
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert face_rows[0]["business_action"] == "known_trigger"

    soft_quality_same_person = _result_for_faces(
        [
            _known_face(
                name="小明",
                person_id="3427976339944670",
                person_type="staff",
                group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                group_name="员工",
                camera_identity_status="name_and_id_matched",
                status="filtered",
                quality_flags=[
                    "multiple_faces",
                    "face_too_small",
                    "face_near_border",
                    "low_identity_confidence",
                ],
                width=36.8,
                height=45.7,
                similarity=0.305,
            )
        ]
    )
    handled, record = await run_case(known_payload, soft_quality_same_person)
    assert handled.result == "known"
    primary = record["final_recognition_decision"]["primary_trigger"]
    assert primary["name"] == "小明"
    assert primary["reason"] == "camera_insightface_same_person_rescue"
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert face_rows[0]["business_action"] == "known_trigger"

    for hard_flag in ["side_face", "blurred", "low_det_score", "head_pitch_bad"]:
        hard_quality_same_person = _result_for_faces(
            [
                _known_face(
                    name="小明",
                    person_id="3427976339944670",
                    person_type="staff",
                    group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                    group_name="员工",
                    camera_identity_status="name_and_id_matched",
                    status="filtered",
                    quality_flags=["face_too_small", hard_flag],
                    width=36.8,
                    height=45.7,
                    similarity=0.305,
                )
            ]
        )
        handled, record = await run_case(known_payload, hard_quality_same_person)
        assert handled.result == "filtered"
        assert record["final_recognition_decision"]["action"] == "suppress"
        assert hard_flag in record["final_recognition_decision"]["suppressed_faces"][0]["reason"]

    known_event_low_quality_unknown = _result_for_faces(
        [
            _unknown_face(
                face_index=0,
                quality_flags=["face_near_border", "low_identity_confidence"],
                border_margin_ratio=0.01,
            )
        ]
    )
    handled, record = await run_case(known_payload, known_event_low_quality_unknown)
    assert handled.result == "filtered"
    assert record["final_recognition_decision"]["action"] == "suppress"
    assert (
        record["final_recognition_decision"]["suppressed_faces"][0]["reason"]
        == "low_quality_unknown:face_near_border"
    )

    conflict_person = _result_for_faces(
        [
            _known_face(
                name="苏苏",
                person_id="3785841386866689",
                person_type="member",
                group_id="c1e42a1f2531467bae464da8a79dad53",
                group_name="会员",
                camera_identity_status="identity_conflict",
            )
        ]
    )
    handled, record = await run_case(known_payload, conflict_person)
    assert handled.result == "known"
    assert record["camera_result"] == "known"
    assert record["final_recognition_decision"]["primary_trigger"]["name"] == "苏苏"
    assert record["final_recognition_decision"]["primary_trigger"]["person_type"] == "member"

    background_a_capture_b = _result_for_faces(
        [
            _known_face(
                name="小明",
                person_id="3427976339944670",
                person_type="staff",
                group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                group_name="员工",
                camera_identity_status="name_and_id_matched",
                image_source="background",
            ),
            _known_face(
                name="苏苏",
                person_id="3785841386866689",
                person_type="member",
                group_id="c1e42a1f2531467bae464da8a79dad53",
                group_name="会员",
                camera_identity_status="identity_conflict",
                image_source="capture",
                source_role="camera_target_crop",
            ),
        ]
    )
    handled, record = await run_case(known_payload, background_a_capture_b)
    assert handled.result == "known"
    assert [item["trigger"]["name"] for item in record["final_trigger_results"]] == ["苏苏"]
    assert record["final_recognition_decision"]["suppressed_faces"][0]["reason"] == "overridden_by_capture_target"

    capture_small_camera_match = _known_face(
        name="小明",
        person_id="3427976339944670",
        person_type="staff",
        group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
        group_name="员工",
        camera_identity_status="name_and_id_matched",
        image_source="capture",
        status="filtered",
        quality_flags=["face_too_small"],
        width=43.0,
        height=55.0,
        similarity=0.318,
    )
    handled, record = await run_case(
        known_payload,
        _result_for_faces([
            _unknown_face(face_index=1, width=96.0, height=66.0),
            capture_small_camera_match,
        ]),
    )
    assert handled.result == "known"
    assert record["final_recognition_decision"]["primary_trigger"]["name"] == "小明"
    assert record["final_recognition_decision"]["primary_trigger"]["face_key"] == "capture:0"
    assert record["final_recognition_decision"]["suppressed_faces"][0]["reason"] == "extra_unknown_too_small_for_known_event"

    side_capture_camera_match = _known_face(
        name="小明",
        person_id="3427976339944670",
        person_type="staff",
        group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
        group_name="员工",
        camera_identity_status="name_and_id_matched",
        image_source="capture",
        status="filtered",
        quality_flags=["face_too_small", "side_face"],
        width=43.0,
        height=55.0,
        similarity=0.318,
    )
    handled, record = await run_case(known_payload, _result_for_faces([side_capture_camera_match]))
    assert handled.result == "filtered"
    assert record["final_recognition_decision"]["action"] == "suppress"
    assert "side_face" in record["final_recognition_decision"]["suppressed_faces"][0]["reason"]

    filter_env = dict(env)
    filter_env["FACE_RECHECK_MODE"] = "filter"
    head_pitch_bad = _result_for_faces(
        [_suppressed_face(reason="head_pitch_bad", head_pitch=-60.9)],
        mode="filter",
    )
    with patched_env(filter_env), tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(p6s_events.face_recheck, "run_face_recheck", return_value=head_pitch_bad):
            handled = await p6s_events.handle_event(
                with_capture_image(known_payload),
                request_meta=request_meta,
                root=Path(temp_dir),
                notify=False,
            )
        assert handled.record_file is not None
        record = json.loads(handled.record_file.path.read_text(encoding="utf-8"))
    assert handled.result == "filtered"
    assert record["final_recognition_decision"]["action"] == "suppress"
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert face_rows[0]["business_action"] == "suppressed"
    assert "head_pitch_bad" in face_rows[0]["suppress_reason"]
    assert record["face_recheck"]["faces"][0]["selected_face"]["head_pitch"] == -60.9

    handled, record = await run_case(stranger_payload, same_person)
    assert handled.result == "known"
    assert record["result"] == "known"
    assert record["camera_result"] == "stranger"
    assert record["final_recognition_decision"]["primary_trigger"]["kind"] == "known"

    class_member_match = _result_for_faces(
        [
            _known_face(
                name="杜全浩紫发会员",
                person_id="2026070501",
                person_type="class_member",
                group_id="",
                group_name="上课会员",
                camera_identity_status="camera_unknown",
            )
        ]
    )
    handled, record = await run_case(stranger_payload, class_member_match)
    assert handled.result == "known"
    primary = record["final_recognition_decision"]["primary_trigger"]
    assert primary["kind"] == "known"
    assert primary["person_type"] == "class_member"
    assert primary["group_name"] == "上课会员"
    assert record["final_trigger_results"][0]["title"] == "📚 上课会员入场提醒"
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert face_rows[0]["gallery_person_type"] == "class_member"
    assert face_rows[0]["gallery_group_name"] == "上课会员"
    assert face_rows[0]["business_action"] == "known_trigger"

    unknown_face = _result_for_faces([_unknown_face(face_index=0)])
    handled, record = await run_case(stranger_payload, unknown_face)
    assert handled.result == "stranger"
    assert record["result"] == "stranger"
    assert record["final_recognition_decision"]["primary_trigger"]["kind"] == "stranger"
    assert "border_margin_ratio" in record["face_recheck"]["faces"][0]["selected_face"]
    assert "motion_blur_score" in record["face_recheck"]["faces"][0]["selected_face"]

    near_border_unknown = _result_for_faces(
        [
            _unknown_face(
                face_index=0,
                quality_flags=["face_near_border", "low_identity_confidence"],
                border_margin_ratio=0.01,
            )
        ]
    )
    handled, record = await run_case(stranger_payload, near_border_unknown)
    assert handled.result == "filtered"
    assert record["final_recognition_decision"]["action"] == "suppress"
    assert record["final_recognition_decision"]["suppressed_faces"][0]["reason"] == "low_quality_unknown:face_near_border"
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert face_rows[0]["business_action"] == "suppressed"
    assert face_rows[0]["suppress_reason"] == "low_quality_unknown:face_near_border"

    motion_blur_observed = _result_for_faces([_unknown_face(face_index=0, motion_blur_score=0.001)])
    handled, record = await run_case(stranger_payload, motion_blur_observed)
    assert handled.result == "stranger"
    assert record["final_recognition_decision"]["primary_trigger"]["kind"] == "stranger"

    motion_blur_unknown = _result_for_faces(
        [
            _unknown_face(
                face_index=0,
                quality_flags=["motion_blur", "low_identity_confidence"],
                motion_blur_score=0.001,
            )
        ]
    )
    handled, record = await run_case(stranger_payload, motion_blur_unknown)
    assert handled.result == "filtered"
    assert record["final_recognition_decision"]["suppressed_faces"][0]["reason"] == "low_quality_unknown:motion_blur"

    low_identity_only = _result_for_faces([_unknown_face(face_index=0, quality_flags=["low_identity_confidence"])])
    handled, record = await run_case(stranger_payload, low_identity_only)
    assert handled.result == "stranger"
    assert record["final_recognition_decision"]["primary_trigger"]["kind"] == "stranger"

    high_confidence_known_near_border = _result_for_faces(
        [
            _known_face(
                name="小明",
                person_id="3427976339944670",
                person_type="staff",
                group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                group_name="员工",
                camera_identity_status="camera_unknown",
                quality_flags=["face_near_border"],
            )
        ]
    )
    handled, record = await run_case(stranger_payload, high_confidence_known_near_border)
    assert handled.result == "known"
    assert record["final_recognition_decision"]["primary_trigger"]["kind"] == "known"

    multi_known_unknown = _result_for_faces(
        [
            _known_face(
                name="小明",
                person_id="3427976339944670",
                person_type="staff",
                group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                group_name="员工",
                camera_identity_status="camera_unknown",
                face_index=0,
            ),
            _unknown_face(face_index=1),
        ]
    )
    handled, record = await run_case(stranger_payload, multi_known_unknown)
    assert handled.result == "known"
    assert [item["trigger"]["kind"] for item in record["final_trigger_results"]] == ["known", "stranger"]
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert [row["business_action"] for row in face_rows] == ["known_trigger", "stranger_trigger"]

    background_unknown_with_capture_unknown = _result_for_faces(
        [
            _unknown_face(face_index=0),
            _unknown_face(
                face_index=0,
                image_source="capture",
                source_role="camera_target_crop",
            ),
        ]
    )
    handled, record = await run_case(stranger_payload, background_unknown_with_capture_unknown)
    assert handled.result == "stranger"
    assert [item["trigger"]["kind"] for item in record["final_trigger_results"]] == ["stranger"]
    assert record["final_recognition_decision"]["suppressed_faces"][0]["face_key"] == "capture:0"
    assert record["final_recognition_decision"]["suppressed_faces"][0]["reason"] == "capture_supporting_evidence_only"
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert [row["source_role"] for row in face_rows] == ["scene_face", "camera_target_crop"]
    assert [row["business_action"] for row in face_rows] == ["stranger_trigger", "supporting_evidence"]

    multi_known_unknown_with_capture_unknown = _result_for_faces(
        [
            _known_face(
                name="小明",
                person_id="3427976339944670",
                person_type="staff",
                group_id="4dcafc2c9fbd4d1fa267ccbf145c8861",
                group_name="员工",
                camera_identity_status="camera_unknown",
                face_index=0,
            ),
            _unknown_face(face_index=1),
            _unknown_face(
                face_index=0,
                image_source="capture",
                source_role="camera_target_crop",
            ),
        ]
    )
    handled, record = await run_case(stranger_payload, multi_known_unknown_with_capture_unknown)
    assert handled.result == "known"
    assert [item["trigger"]["kind"] for item in record["final_trigger_results"]] == ["known", "stranger"]
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert [row["business_action"] for row in face_rows] == [
        "known_trigger",
        "stranger_trigger",
        "supporting_evidence",
    ]

    multi_unknown = _result_for_faces([_unknown_face(face_index=0), _unknown_face(face_index=1)])
    handled, record = await run_case(stranger_payload, multi_unknown)
    assert handled.result == "stranger"
    assert [item["trigger"]["kind"] for item in record["final_trigger_results"]] == ["stranger", "stranger"]

    side_face = _result_for_faces([_suppressed_face(reason="side_face")], mode="filter")
    with patched_env(filter_env), tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(p6s_events.face_recheck, "run_face_recheck", return_value=side_face):
            handled = await p6s_events.handle_event(
                with_capture_image(known_payload),
                request_meta=request_meta,
                root=Path(temp_dir),
                notify=False,
            )
        assert handled.record_file is not None
        record = json.loads(handled.record_file.path.read_text(encoding="utf-8"))
    assert handled.result == "filtered"
    assert record["result"] == "filtered"
    assert record["final_recognition_decision"]["action"] == "suppress"
    face_rows = recognition_monitor.build_event_face_rows(record)
    assert face_rows[0]["business_action"] == "suppressed"
    assert "side_face" in face_rows[0]["suppress_reason"]


def _mock_recheck_result() -> face_recheck.FaceRecheckResult:
    selected_face = face_recheck.DetectedFaceSummary(
        index=0,
        bbox=(1.0, 2.0, 101.0, 122.0),
        det_score=0.91,
        width=100.0,
        height=120.0,
        blur_score=132.4,
        border_margin_ratio=0.2,
        motion_blur_score=12.0,
        frontal_score=0.12,
        head_pitch=None,
        quality_flags=[],
    )
    gallery_match = face_recheck.GalleryMatch(
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
        accepted_threshold=0.5,
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
    )
    return face_recheck.FaceRecheckResult(
        enabled=True,
        mode="shadow",
        status="passed",
        decision="allow_original",
        reason="quality_passed",
        image_source="background",
        face_count=1,
        selected_face=selected_face,
        gallery_match=gallery_match,
        elapsed_ms=12,
        thresholds=face_recheck.FaceRecheckThresholds(
            det_score_threshold=0.65,
            min_face_width=80,
            min_face_height=80,
            blur_threshold=80.0,
            frontal_max_yaw_score=0.35,
            head_pitch_min=-45.0,
            similarity_threshold=0.5,
            camera_match_similarity_threshold=0.3,
            camera_match_gap_threshold=0.03,
            camera_match_rescue_min_face_width=40,
            camera_match_rescue_min_face_height=50,
            known_extra_unknown_min_face_width=80,
            known_extra_unknown_min_face_height=80,
            border_margin_ratio=0.02,
            motion_blur_threshold=None,
            low_identity_similarity=0.28,
            low_identity_gap=0.04,
            similarity_margin=0.03,
        ),
        faces=[
            face_recheck.FaceRecheckFaceResult(
                image_source="background",
                face_index=0,
                face_key="background:0",
                selected_face=selected_face,
                status="passed",
                reason="quality_passed",
                gallery_match=gallery_match,
            ),
        ],
        primary_face_key="background:0",
        accepted_face_count=1,
        has_identity_conflict=False,
        camera_target_face_status="camera_unknown",
    )


def _result_for_faces(
    faces: list[face_recheck.FaceRecheckFaceResult],
    *,
    mode: str = "verify_and_override",
) -> face_recheck.FaceRecheckResult:
    base = _mock_recheck_result()
    selected = faces[0].selected_face if faces else None
    gallery = faces[0].gallery_match if faces else None
    return replace(
        base,
        mode=mode,
        status=faces[0].status if faces else "filtered",
        reason=faces[0].reason if faces else "no_face",
        image_source=faces[0].image_source if faces else "none",
        face_count=sum(1 for face in faces if face.selected_face is not None),
        selected_face=selected,
        gallery_match=gallery,
        faces=faces,
        primary_face_key=faces[0].face_key if faces else None,
        accepted_face_count=sum(1 for face in faces if face.gallery_match and face.gallery_match.accepted),
        has_identity_conflict=any(
            face.gallery_match
            and face.gallery_match.accepted
            and face.gallery_match.camera_identity_status == "identity_conflict"
            for face in faces
        ),
        camera_target_face_status=(
            "accepted_match"
            if any(
                face.gallery_match
                and face.gallery_match.accepted
                and face.gallery_match.camera_identity_status in {"name_matched", "id_matched", "name_and_id_matched"}
                for face in faces
            )
            else "camera_unknown"
        ),
    )


def _known_face(
    *,
    name: str,
    person_id: str,
    person_type: str,
    group_id: str,
    group_name: str,
    camera_identity_status: str,
    face_index: int = 0,
    similarity: float = 0.91,
    image_source: str = "background",
    source_role: str | None = None,
    status: str = "passed",
    quality_flags: list[str] | None = None,
    width: float = 100.0,
    height: float = 120.0,
) -> face_recheck.FaceRecheckFaceResult:
    selected_face = _detected_face(
        face_index,
        quality_flags=quality_flags,
        width=width,
        height=height,
    )
    gallery_match = face_recheck.GalleryMatch(
        person_id=person_id,
        credential_no=person_id,
        credential_type="2",
        name=name,
        sex="0",
        person_type=person_type,  # type: ignore[arg-type]
        group_id=group_id,
        group_name=group_name,
        similarity=similarity,
        second_similarity=0.20,
        accepted=True,
        accepted_threshold=0.50,
        camera_identity_status=camera_identity_status,  # type: ignore[arg-type]
        candidates=[
            face_recheck.GalleryCandidate(
                rank=1,
                person_id=person_id,
                credential_no=person_id,
                credential_type="2",
                name=name,
                sex="0",
                person_type=person_type,  # type: ignore[arg-type]
                group_id=group_id,
                group_name=group_name,
                similarity=similarity,
            )
        ],
    )
    return face_recheck.FaceRecheckFaceResult(
        image_source=image_source,  # type: ignore[arg-type]
        face_index=face_index,
        face_key=f"{image_source}:{face_index}",
        selected_face=selected_face,
        status=status,  # type: ignore[arg-type]
        reason=",".join(selected_face.quality_flags) if selected_face.quality_flags else "quality_passed",
        gallery_match=gallery_match,
        source_role=source_role,  # type: ignore[arg-type]
    )


def _unknown_face(
    *,
    face_index: int,
    image_source: str = "background",
    source_role: str | None = None,
    width: float = 100.0,
    height: float = 120.0,
    quality_flags: list[str] | None = None,
    border_margin_ratio: float = 0.2,
    motion_blur_score: float = 12.0,
) -> face_recheck.FaceRecheckFaceResult:
    selected_face = _detected_face(
        face_index,
        width=width,
        height=height,
        quality_flags=quality_flags,
        border_margin_ratio=border_margin_ratio,
        motion_blur_score=motion_blur_score,
    )
    return face_recheck.FaceRecheckFaceResult(
        image_source=image_source,  # type: ignore[arg-type]
        face_index=face_index,
        face_key=f"{image_source}:{face_index}",
        selected_face=selected_face,
        status="passed",
        reason=",".join(selected_face.quality_flags) if selected_face.quality_flags else "quality_passed",
        gallery_match=None,
        source_role=source_role,  # type: ignore[arg-type]
    )


def _suppressed_face(
    *,
    reason: str,
    head_pitch: float | None = None,
) -> face_recheck.FaceRecheckFaceResult:
    return face_recheck.FaceRecheckFaceResult(
        image_source="background",
        face_index=0,
        face_key="background:0",
        selected_face=_detected_face(0, quality_flags=[reason], head_pitch=head_pitch),
        status="filtered",
        reason=reason,
        gallery_match=None,
    )


def _detected_face(
    face_index: int,
    *,
    quality_flags: list[str] | None = None,
    width: float = 100.0,
    height: float = 120.0,
    head_pitch: float | None = None,
    border_margin_ratio: float = 0.2,
    motion_blur_score: float = 12.0,
) -> face_recheck.DetectedFaceSummary:
    x1 = 1.0 + (face_index * 20.0)
    y1 = 2.0
    return face_recheck.DetectedFaceSummary(
        index=face_index,
        bbox=(x1, y1, x1 + width, y1 + height),
        det_score=0.91,
        width=width,
        height=height,
        blur_score=132.4,
        border_margin_ratio=border_margin_ratio,
        motion_blur_score=motion_blur_score,
        frontal_score=0.12,
        head_pitch=head_pitch,
        quality_flags=quality_flags or [],
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
    face_row = {
        "face_key": "background:0",
        "image_source": "background",
        "face_index": 0,
        "bbox": [1, 2, 101, 122],
        "face_width": 100,
        "face_height": 120,
        "det_score": 0.91,
        "blur_score": 132.4,
        "frontal_score": 0.12,
        "quality_flags": [],
        "recheck_status": "passed",
        "recheck_reason": "quality_passed",
        "gallery_accepted": True,
        "gallery_name": "小明",
        "gallery_person_id": "3427976339944670",
        "gallery_person_type": "staff",
        "gallery_group_name": "员工",
        "gallery_similarity": 0.91,
        "gallery_second_similarity": 0.42,
        "gallery_camera_identity_status": "camera_unknown",
        "gallery_top5_candidates": [],
        "crop_relative_path": monitor_row["capture_relative_path"],
        "crop_content_type": "image/jpeg",
    }
    event_dto = recognition_monitor.row_to_event(monitor_row, include_detail=True, faces=[face_row])
    assert event_dto["event_key"] == monitor_row["event_dedupe_key"]
    assert event_dto["camera"]["name"] == "小明"
    assert event_dto["images"]["capture"]["api_url"].startswith("/api/recognition-monitor/images?")
    assert event_dto["faces"][0]["face_key"] == "background:0"
    assert event_dto["faces"][0]["crop"]["api_url"].startswith("/api/recognition-monitor/images?")
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


def _post_plain_texts(payload: dict) -> list[str]:
    return [
        item.get("text", "")
        for line in _post_lines(payload)
        for item in line
        if item.get("tag") == "text"
    ]


if __name__ == "__main__":
    asyncio.run(validate())
