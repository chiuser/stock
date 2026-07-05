"""P6S event parsing, routing, storage, notification, and Ack generation."""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services import attendance, event_store, face_recheck, feishu, image_links, recognition_monitor


@dataclass(frozen=True)
class PersonRole:
    code: str
    name: str
    group_id: str
    group_name: str
    notification_title: str


@dataclass(frozen=True)
class MatchedPerson:
    name: str
    person_id: str
    ack_person_id: int
    camera_person_id: str | None
    person_name_missing: bool
    person_id_missing: bool
    role: PersonRole
    raw: dict[str, Any]


@dataclass(frozen=True)
class DecodedEventImage:
    kind: str
    source: str
    image_bytes: bytes
    expected_md5: str


@dataclass(frozen=True)
class SavedFaceRecoImage:
    kind: str
    source: str
    stored_image: event_store.StoredImage | None
    created_link: image_links.CreatedImageLink | None
    image_record: dict[str, Any]
    link_record: dict[str, Any] | None
    notify_message: str


@dataclass(frozen=True)
class SavedFaceRecoImages:
    background: SavedFaceRecoImage | None
    capture: SavedFaceRecoImage | None

    def primary(self) -> SavedFaceRecoImage | None:
        for image in (self.background, self.capture):
            if image and image.stored_image:
                return image
        return None

    def image_records(self) -> dict[str, dict[str, Any]]:
        return {
            image.kind: image.image_record
            for image in (self.background, self.capture)
            if image is not None
        }

    def link_records(self) -> dict[str, dict[str, Any]]:
        return {
            image.kind: image.link_record
            for image in (self.background, self.capture)
            if image is not None and image.link_record is not None
        }

    def notify_message(self, default: str) -> str:
        messages = [
            image.notify_message
            for image in (self.background, self.capture)
            if image is not None and image.notify_message
        ]
        return "; ".join(messages) or default


@dataclass(frozen=True)
class EventHandleResult:
    ack: dict[str, Any]
    result: str
    identity: event_store.EventIdentity
    raw_file: event_store.StoredFile
    record_file: event_store.StoredFile | None = None
    image: event_store.StoredImage | None = None
    link: image_links.CreatedImageLink | None = None
    feishu_result: dict[str, Any] | None = None
    attendance_result: dict[str, Any] | None = None
    duplicate: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "result": self.result,
            "duplicate": self.duplicate,
            "dedupe_key": self.identity.dedupe_key,
            "raw_file": self.raw_file.to_dict(),
            "record_file": self.record_file.to_dict() if self.record_file else None,
            "image": self.image.to_dict() if self.image else None,
            "link": _link_to_dict(self.link) if self.link else None,
            "feishu": self.feishu_result,
            "attendance": self.attendance_result,
            "ack": self.ack,
        }


async def handle_event(
    payload: dict[str, Any],
    *,
    request_meta: event_store.RequestMeta | None = None,
    root: Path | str | None = None,
    notify: bool = True,
) -> EventHandleResult:
    identity = event_store.build_event_identity(payload)
    raw_file = event_store.persist_raw_event(
        payload,
        request_meta=request_meta,
        identity=identity,
        root=root,
    )
    duplicate = event_store.processing_record_exists(identity, root=root)
    if duplicate:
        attendance_result = attendance.safe_increment_delivery_count(identity.dedupe_key)
        return EventHandleResult(
            ack=_ack_for_payload(payload, None, None),
            result="duplicate",
            identity=identity,
            raw_file=raw_file,
            feishu_result=_notification_skipped("duplicate event"),
            attendance_result=attendance_result,
            duplicate=True,
        )

    operator = identity.operator
    if operator == "heartbeat":
        ack = _heartbeat_ack(payload)
        record_file = _write_record(
            identity,
            {"result": "heartbeat", "ack": _ack_summary(ack)},
            root=root,
        )
        return EventHandleResult(
            ack=ack,
            result="heartbeat",
            identity=identity,
            raw_file=raw_file,
            record_file=record_file,
            feishu_result=_notification_skipped("heartbeat"),
        )

    if operator != "FaceReco":
        ack = _generic_ack(operator)
        record_file = _write_record(
            identity,
            {"result": "ignored", "ack": _ack_summary(ack)},
            root=root,
        )
        return EventHandleResult(
            ack=ack,
            result="ignored",
            identity=identity,
            raw_file=raw_file,
            record_file=record_file,
            feishu_result=_notification_skipped("ignored operator"),
        )

    return _handle_face_reco(
        payload,
        identity=identity,
        raw_file=raw_file,
        root=root,
        notify=notify,
    )


def _handle_face_reco(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    root: Path | str | None,
    notify: bool,
) -> EventHandleResult:
    info = payload.get("info") or {}
    person_info_value = payload.get("personInfo") or info.get("personInfo")
    match_number = _parse_int(info.get("matchNumber"))
    route_result = _route_face_reco(match_number, person_info_value)

    if route_result == "known":
        return _handle_known_face(
            payload,
            identity=identity,
            raw_file=raw_file,
            person_info_value=person_info_value,
            match_number=match_number,
            root=root,
            notify=notify,
        )
    if route_result == "parse_error":
        return _handle_parse_error(
            payload,
            identity=identity,
            raw_file=raw_file,
            root=root,
            notify=notify,
            message="matchNumber > 0 but personInfo is empty or invalid",
            match_number=match_number,
        )
    return _handle_stranger(
        payload,
        identity=identity,
        raw_file=raw_file,
        root=root,
        notify=notify,
        match_number=match_number,
        match_number_missing=match_number is None,
    )


def _handle_known_face(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    person_info_value: Any,
    match_number: int | None,
    root: Path | str | None,
    notify: bool,
) -> EventHandleResult:
    info = payload.get("info") or {}
    person = _parse_matched_person(person_info_value)
    person_type = attendance.person_type_for_role(person.role.code)
    person_ref_id = None if person.person_id_missing else person.person_id
    if person_type in {"member", "coach", "staff"} and not person_ref_id:
        person_type = "unknown_known"
    face_images = _save_face_reco_images(
        info,
        identity=identity,
        root=root,
        category="faces",
        error_prefix="已匹配人脸图片",
    )
    primary_image = face_images.primary()
    representative_image = _representative_image(face_images)
    recheck_result = _run_face_recheck_for_event(
        identity=identity,
        route_result="known",
        face_images=face_images,
        camera_person=_matched_person_summary(person),
        root=root,
    )
    final_decision = face_recheck.build_final_recognition_decision(
        camera_result="known",
        camera_person=_matched_person_summary(person),
        recheck_result=recheck_result,
    )
    recheck_shadow_result = _notify_face_recheck_shadow_for_event(
        identity=identity,
        route_result="known",
        face_images=face_images,
        camera_person=_matched_person_summary(person),
        notify=notify,
        recheck_result=recheck_result,
        final_decision=final_decision,
    )
    if final_decision.action != "allow_original":
        return _handle_final_recognition_decision(
            payload,
            identity=identity,
            raw_file=raw_file,
            root=root,
            notify=notify,
            original_result="known",
            original_matched_person=person,
            face_images=face_images,
            primary_image=primary_image,
            representative_image=representative_image,
            recheck_result=recheck_result,
            recheck_shadow_result=recheck_shadow_result,
            final_decision=final_decision,
            match_number=match_number,
            extra_record={},
        )
    draft = attendance.build_known_draft(
        identity=identity,
        raw_file=raw_file,
        person_type=person_type,
        person_ref_id=person_ref_id,
        name=person.name,
        camera_person_id=person.camera_person_id,
        face_group_id=person.role.group_id,
        face_group_name=person.role.group_name,
        match_number=match_number,
        stored_image=primary_image.stored_image if primary_image else None,
        image_url=_image_view_url(primary_image),
        token_hash=_image_token_hash(primary_image),
        image_source=_image_source(primary_image),
    )
    db_result = attendance.safe_record_event(draft)
    ack = _face_reco_ack(
        payload,
        matched_person=person,
        stored_image=_stored_image_path(primary_image),
    )
    feishu_result = _notification_skipped("known notification disabled")
    should_send = notify and _notify_known_enabled() and db_result.should_notify
    skip_reason = db_result.suppressed_reason
    if should_send:
        feishu_result = _safe_notify(
            feishu.notify_known_face,
            name=person.name,
            person_id=person.person_id,
            device_sn=identity.serial_number,
            event_time=identity.event_time,
            event_id=identity.event_id,
            role_name=person.role.name if person.role.code != "unknown" else "",
            title=person.role.notification_title,
            storage_path=_stored_image_path(primary_image),
            view_url=_image_view_url(primary_image),
            background_view_url=_image_view_url(face_images.background),
            capture_view_url=_image_view_url(face_images.capture),
        )
    else:
        skip_reason = skip_reason or ("notify disabled" if not notify else "known notification disabled")
        feishu_result = _notification_skipped(skip_reason)

    notification_record = attendance.safe_record_notification(
        db_result,
        feishu_result=feishu_result,
        should_send=should_send,
        title=person.role.notification_title,
        suppressed_reason=None if should_send else skip_reason,
    )

    record_file = _write_record(
        identity,
        {
            "result": "known",
            "matched_person": {
                "name": person.name,
                "id": person.person_id,
                "person_id": person.ack_person_id,
                "camera_person_id": person.camera_person_id,
                "person_name_missing": person.person_name_missing,
                "person_id_missing": person.person_id_missing,
                "person_role": person.role.code,
                "person_role_name": person.role.name,
                "person_group_id": person.role.group_id,
                "person_group_name": person.role.group_name,
                "notification_title": person.role.notification_title,
            },
            "image": representative_image.image_record if representative_image else None,
            "link": _link_to_dict(primary_image.created_link) if primary_image else None,
            "images": face_images.image_records(),
            "links": face_images.link_records(),
            "face_recheck": recheck_result.to_dict(),
            "face_recheck_shadow_feishu": _notify_result_summary(recheck_shadow_result),
            "feishu": feishu_result,
            "attendance": db_result.to_dict(),
            "attendance_notification": notification_record,
            "ack": _ack_summary(ack),
        },
        root=root,
    )
    return EventHandleResult(
        ack=ack,
        result="known",
        identity=identity,
        raw_file=raw_file,
        record_file=record_file,
        image=primary_image.stored_image if primary_image else None,
        link=primary_image.created_link if primary_image else None,
        feishu_result=feishu_result,
        attendance_result=db_result.to_dict(),
    )


def _handle_stranger(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    root: Path | str | None,
    notify: bool,
    match_number: int | None,
    match_number_missing: bool,
) -> EventHandleResult:
    info = payload.get("info") or {}
    feishu_result: dict[str, Any]
    face_images = _save_face_reco_images(
        info,
        identity=identity,
        root=root,
        category="strangers",
        error_prefix="未匹配人脸图片",
    )
    primary_image = face_images.primary()
    representative_image = _representative_image(face_images)
    recheck_result = _run_face_recheck_for_event(
        identity=identity,
        route_result="stranger",
        face_images=face_images,
        camera_person=None,
        root=root,
    )
    final_decision = face_recheck.build_final_recognition_decision(
        camera_result="stranger",
        camera_person=None,
        recheck_result=recheck_result,
    )
    recheck_shadow_result = _notify_face_recheck_shadow_for_event(
        identity=identity,
        route_result="stranger",
        face_images=face_images,
        camera_person=None,
        notify=notify,
        recheck_result=recheck_result,
        final_decision=final_decision,
    )
    if final_decision.action != "allow_original":
        return _handle_final_recognition_decision(
            payload,
            identity=identity,
            raw_file=raw_file,
            root=root,
            notify=notify,
            original_result="stranger",
            original_matched_person=None,
            face_images=face_images,
            primary_image=primary_image,
            representative_image=representative_image,
            recheck_result=recheck_result,
            recheck_shadow_result=recheck_shadow_result,
            final_decision=final_decision,
            match_number=match_number,
            extra_record={"match_number_missing": match_number_missing},
        )

    draft = attendance.build_stranger_draft(
        identity=identity,
        raw_file=raw_file,
        stored_image=primary_image.stored_image if primary_image else None,
        image_url=_image_view_url(primary_image),
        token_hash=_image_token_hash(primary_image),
        image_source=_image_source(primary_image),
        match_number=match_number,
    )
    db_result = attendance.safe_record_event(draft)
    should_send = notify and db_result.should_notify
    if not should_send:
        feishu_result = _notification_skipped(
            db_result.suppressed_reason or ("notify disabled" if not notify else "attendance notification suppressed")
        )
    elif primary_image and primary_image.stored_image and primary_image.created_link:
        feishu_result = _notify_unknown(
            notify=notify,
            image_path=primary_image.stored_image.path,
            device_sn=identity.serial_number,
            event_time=identity.event_time,
            event_id=identity.event_id,
            storage_path=str(primary_image.stored_image.path),
            view_url=primary_image.created_link.view_url,
            background_view_url=_image_view_url(face_images.background),
            capture_view_url=_image_view_url(face_images.capture),
        )
    else:
        feishu_result = _notify_error(
            notify=notify,
            message=face_images.notify_message("未匹配人脸图片不可用"),
            identity=identity,
            raw_event_path=raw_file.path,
        )

    notification_record = attendance.safe_record_notification(
        db_result,
        feishu_result=feishu_result,
        should_send=should_send,
        title="‼️ 发现陌生人入场",
        suppressed_reason=None if should_send else feishu_result.get("reason"),
    )

    ack = _face_reco_ack(
        payload,
        matched_person=None,
        stored_image=_stored_image_path(primary_image),
    )
    record_file = _write_record(
        identity,
        {
            "result": "stranger",
            "match_number_missing": match_number_missing,
            "matched_person": {"name": "", "id": ""},
            "image": representative_image.image_record if representative_image else None,
            "link": _link_to_dict(primary_image.created_link) if primary_image else None,
            "images": face_images.image_records(),
            "links": face_images.link_records(),
            "face_recheck": recheck_result.to_dict(),
            "face_recheck_shadow_feishu": _notify_result_summary(recheck_shadow_result),
            "feishu": feishu_result,
            "attendance": db_result.to_dict(),
            "attendance_notification": notification_record,
            "ack": _ack_summary(ack),
        },
        root=root,
    )
    return EventHandleResult(
        ack=ack,
        result="stranger",
        identity=identity,
        raw_file=raw_file,
        record_file=record_file,
        image=primary_image.stored_image if primary_image else None,
        link=primary_image.created_link if primary_image else None,
        feishu_result=feishu_result,
        attendance_result=db_result.to_dict(),
    )


def _handle_parse_error(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    root: Path | str | None,
    notify: bool,
    message: str,
    match_number: int | None,
) -> EventHandleResult:
    info = payload.get("info") or {}
    face_images = _save_face_reco_images(
        info,
        identity=identity,
        root=root,
        category="faces",
        error_prefix="人脸识别事件图片",
    )
    primary_image = face_images.primary()
    representative_image = _representative_image(face_images)
    recheck_result = _run_face_recheck_for_event(
        identity=identity,
        route_result="parse_error",
        face_images=face_images,
        camera_person=None,
        root=root,
    )
    final_decision = face_recheck.build_final_recognition_decision(
        camera_result="parse_error",
        camera_person=None,
        recheck_result=recheck_result,
    )
    recheck_shadow_result = _notify_face_recheck_shadow_for_event(
        identity=identity,
        route_result="parse_error",
        face_images=face_images,
        camera_person=None,
        notify=notify,
        recheck_result=recheck_result,
        final_decision=final_decision,
    )
    if final_decision.action != "allow_original":
        return _handle_final_recognition_decision(
            payload,
            identity=identity,
            raw_file=raw_file,
            root=root,
            notify=notify,
            original_result="parse_error",
            original_matched_person=None,
            face_images=face_images,
            primary_image=primary_image,
            representative_image=representative_image,
            recheck_result=recheck_result,
            recheck_shadow_result=recheck_shadow_result,
            final_decision=final_decision,
            match_number=match_number,
            extra_record={"error": message},
        )
    ack = _face_reco_ack(
        payload,
        matched_person=None,
        stored_image=_stored_image_path(primary_image),
    )
    draft = attendance.build_parse_error_draft(
        identity=identity,
        raw_file=raw_file,
        match_number=match_number,
        stored_image=primary_image.stored_image if primary_image else None,
        image_url=_image_view_url(primary_image),
        token_hash=_image_token_hash(primary_image),
        image_source=_image_source(primary_image),
    )
    db_result = attendance.safe_record_event(draft)
    should_send = notify and db_result.should_notify
    if should_send:
        feishu_result = _notify_error(
            notify=notify,
            message=message,
            identity=identity,
            raw_event_path=raw_file.path,
            storage_path=_stored_image_path(primary_image),
            view_url=_image_view_url(primary_image),
            background_view_url=_image_view_url(face_images.background),
            capture_view_url=_image_view_url(face_images.capture),
        )
    else:
        feishu_result = _notification_skipped(
            db_result.suppressed_reason or ("notify disabled" if not notify else "attendance notification suppressed")
        )
    notification_record = attendance.safe_record_notification(
        db_result,
        feishu_result=feishu_result,
        should_send=should_send,
        title="人员入场提醒",
        suppressed_reason=None if should_send else feishu_result.get("reason"),
    )
    record_file = _write_record(
        identity,
        {
            "result": "parse_error",
            "error": message,
            "matched_person": {"name": "", "id": ""},
            "image": representative_image.image_record if representative_image else None,
            "link": _link_to_dict(primary_image.created_link) if primary_image else None,
            "images": face_images.image_records(),
            "links": face_images.link_records(),
            "face_recheck": recheck_result.to_dict(),
            "face_recheck_shadow_feishu": _notify_result_summary(recheck_shadow_result),
            "feishu": feishu_result,
            "attendance": db_result.to_dict(),
            "attendance_notification": notification_record,
            "ack": _ack_summary(ack),
        },
        root=root,
    )
    return EventHandleResult(
        ack=ack,
        result="parse_error",
        identity=identity,
        raw_file=raw_file,
        record_file=record_file,
        image=primary_image.stored_image if primary_image else None,
        link=primary_image.created_link if primary_image else None,
        feishu_result=feishu_result,
        attendance_result=db_result.to_dict(),
    )


def _handle_final_recognition_decision(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    root: Path | str | None,
    notify: bool,
    original_result: str,
    original_matched_person: MatchedPerson | None,
    face_images: SavedFaceRecoImages,
    primary_image: SavedFaceRecoImage | None,
    representative_image: SavedFaceRecoImage | None,
    recheck_result: face_recheck.FaceRecheckResult,
    recheck_shadow_result: dict[str, Any],
    final_decision: face_recheck.FinalRecognitionDecision,
    match_number: int | None,
    extra_record: dict[str, Any],
) -> EventHandleResult:
    ack = _face_reco_ack(
        payload,
        matched_person=original_matched_person,
        stored_image=_stored_image_path(primary_image),
    )
    if final_decision.action == "suppress":
        feishu_result = _notification_skipped(final_decision.reason)
        record_file = _write_record(
            identity,
            _final_record_payload(
                original_result=original_result,
                result="filtered",
                original_matched_person=original_matched_person,
                representative_image=representative_image,
                primary_image=primary_image,
                face_images=face_images,
                recheck_result=recheck_result,
                recheck_shadow_result=recheck_shadow_result,
                final_decision=final_decision,
                trigger_results=[],
                feishu_result=feishu_result,
                attendance_result={"skipped": True, "reason": final_decision.reason},
                notification_record={"ok": True, "skipped": True, "reason": final_decision.reason},
                ack=ack,
                extra_record=extra_record,
            ),
            root=root,
        )
        return EventHandleResult(
            ack=ack,
            result="filtered",
            identity=identity,
            raw_file=raw_file,
            record_file=record_file,
            image=primary_image.stored_image if primary_image else None,
            link=primary_image.created_link if primary_image else None,
            feishu_result=feishu_result,
            attendance_result={"skipped": True, "reason": final_decision.reason},
        )

    trigger_results = [
        _execute_final_trigger(
            trigger,
            identity=identity,
            raw_file=raw_file,
            notify=notify,
            face_images=face_images,
            primary_image=primary_image,
            match_number=match_number,
        )
        for trigger in final_decision.primary_and_extra_triggers
    ]
    primary_result = trigger_results[0] if trigger_results else {}
    feishu_result = _dict_or_skipped(primary_result.get("feishu"), "final decision had no trigger")
    attendance_result = _dict_or_skipped(primary_result.get("attendance"), "final decision had no attendance")
    notification_record = _dict_or_skipped(
        primary_result.get("attendance_notification"),
        "final decision had no notification",
    )
    record_file = _write_record(
        identity,
            _final_record_payload(
                original_result=original_result,
                result=_final_business_result(final_decision, original_result),
                original_matched_person=original_matched_person,
                representative_image=representative_image,
                primary_image=primary_image,
            face_images=face_images,
            recheck_result=recheck_result,
            recheck_shadow_result=recheck_shadow_result,
            final_decision=final_decision,
            trigger_results=trigger_results,
            feishu_result=feishu_result,
            attendance_result=attendance_result,
            notification_record=notification_record,
            ack=ack,
            extra_record=extra_record,
        ),
        root=root,
    )
    return EventHandleResult(
        ack=ack,
        result=final_decision.primary_trigger.kind if final_decision.primary_trigger else original_result,
        identity=identity,
        raw_file=raw_file,
        record_file=record_file,
        image=primary_image.stored_image if primary_image else None,
        link=primary_image.created_link if primary_image else None,
        feishu_result=feishu_result,
        attendance_result=attendance_result,
    )


def _execute_final_trigger(
    trigger: face_recheck.FinalRecognitionTrigger,
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    notify: bool,
    face_images: SavedFaceRecoImages,
    primary_image: SavedFaceRecoImage | None,
    match_number: int | None,
) -> dict[str, Any]:
    event_dedupe_key = _trigger_event_dedupe_key(identity, trigger)
    if trigger.kind == "known":
        title = _title_for_person_type(trigger.person_type)
        role_name = trigger.group_name or _role_name_for_person_type(trigger.person_type)
        draft = attendance.build_known_draft(
            identity=identity,
            raw_file=raw_file,
            person_type=trigger.person_type or "unknown_known",
            person_ref_id=trigger.person_id,
            name=trigger.name or "未知姓名",
            camera_person_id=None,
            face_group_id=trigger.group_id,
            face_group_name=trigger.group_name,
            match_number=match_number,
            stored_image=primary_image.stored_image if primary_image else None,
            image_url=_image_view_url(primary_image),
            token_hash=_image_token_hash(primary_image),
            image_source=_image_source(primary_image),
            event_dedupe_key=event_dedupe_key,
        )
        db_result = attendance.safe_record_event(draft)
        should_send = notify and _notify_known_enabled() and db_result.should_notify
        skip_reason = db_result.suppressed_reason
        if should_send:
            feishu_result = _safe_notify(
                feishu.notify_known_face,
                name=trigger.name or "未知姓名",
                person_id=trigger.person_id or "",
                device_sn=identity.serial_number,
                event_time=identity.event_time,
                event_id=identity.event_id,
                role_name=role_name,
                title=title,
                storage_path=_stored_image_path(primary_image),
                view_url=_image_view_url(primary_image),
                background_view_url=_image_view_url(face_images.background),
                capture_view_url=_image_view_url(face_images.capture),
            )
        else:
            skip_reason = skip_reason or ("notify disabled" if not notify else "known notification disabled")
            feishu_result = _notification_skipped(skip_reason)
        notification_record = attendance.safe_record_notification(
            db_result,
            feishu_result=feishu_result,
            should_send=should_send,
            title=title,
            suppressed_reason=None if should_send else skip_reason,
        )
        return _trigger_result(trigger, db_result, feishu_result, notification_record, should_send, title, event_dedupe_key)

    draft = attendance.build_stranger_draft(
        identity=identity,
        raw_file=raw_file,
        stored_image=primary_image.stored_image if primary_image else None,
        image_url=_image_view_url(primary_image),
        token_hash=_image_token_hash(primary_image),
        image_source=_image_source(primary_image),
        match_number=match_number,
        event_dedupe_key=event_dedupe_key,
    )
    db_result = attendance.safe_record_event(draft)
    should_send = notify and db_result.should_notify
    if not should_send:
        feishu_result = _notification_skipped(
            db_result.suppressed_reason or ("notify disabled" if not notify else "attendance notification suppressed")
        )
    elif primary_image and primary_image.stored_image and primary_image.created_link:
        feishu_result = _notify_unknown(
            notify=notify,
            image_path=primary_image.stored_image.path,
            device_sn=identity.serial_number,
            event_time=identity.event_time,
            event_id=identity.event_id,
            storage_path=str(primary_image.stored_image.path),
            view_url=primary_image.created_link.view_url,
            background_view_url=_image_view_url(face_images.background),
            capture_view_url=_image_view_url(face_images.capture),
        )
    else:
        feishu_result = _notification_skipped("unknown face image unavailable")
    notification_record = attendance.safe_record_notification(
        db_result,
        feishu_result=feishu_result,
        should_send=should_send,
        title="‼️ 发现陌生人入场",
        suppressed_reason=None if should_send else feishu_result.get("reason"),
    )
    return _trigger_result(
        trigger,
        db_result,
        feishu_result,
        notification_record,
        should_send,
        "‼️ 发现陌生人入场",
        event_dedupe_key,
    )


def _trigger_result(
    trigger: face_recheck.FinalRecognitionTrigger,
    db_result: attendance.AttendanceRecordResult,
    feishu_result: dict[str, Any],
    notification_record: dict[str, Any],
    should_send: bool,
    title: str,
    event_dedupe_key: str,
) -> dict[str, Any]:
    return {
        "trigger": trigger.to_dict(),
        "event_dedupe_key": event_dedupe_key,
        "attendance": db_result.to_dict(),
        "feishu": feishu_result,
        "attendance_notification": notification_record,
        "should_send": should_send,
        "title": title,
    }


def _final_record_payload(
    *,
    original_result: str,
    result: str,
    original_matched_person: MatchedPerson | None,
    representative_image: SavedFaceRecoImage | None,
    primary_image: SavedFaceRecoImage | None,
    face_images: SavedFaceRecoImages,
    recheck_result: face_recheck.FaceRecheckResult,
    recheck_shadow_result: dict[str, Any],
    final_decision: face_recheck.FinalRecognitionDecision,
    trigger_results: list[dict[str, Any]],
    feishu_result: dict[str, Any],
    attendance_result: dict[str, Any],
    notification_record: dict[str, Any],
    ack: dict[str, Any],
    extra_record: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "result": result,
        "camera_result": original_result,
        "matched_person": _matched_person_record(original_matched_person),
        "image": representative_image.image_record if representative_image else None,
        "link": _link_to_dict(primary_image.created_link) if primary_image else None,
        "images": face_images.image_records(),
        "links": face_images.link_records(),
        "face_recheck": recheck_result.to_dict(),
        "final_recognition_decision": final_decision.to_dict(),
        "final_trigger_results": trigger_results,
        "face_recheck_shadow_feishu": _notify_result_summary(recheck_shadow_result),
        "feishu": feishu_result,
        "attendance": attendance_result,
        "attendance_notification": notification_record,
        "ack": _ack_summary(ack),
    }
    payload.update(extra_record)
    return payload


def _matched_person_record(person: MatchedPerson | None) -> dict[str, Any]:
    if person is None:
        return {"name": "", "id": ""}
    return {
        "name": person.name,
        "id": person.person_id,
        "person_id": person.ack_person_id,
        "camera_person_id": person.camera_person_id,
        "person_name_missing": person.person_name_missing,
        "person_id_missing": person.person_id_missing,
        "person_role": person.role.code,
        "person_role_name": person.role.name,
        "person_group_id": person.role.group_id,
        "person_group_name": person.role.group_name,
        "notification_title": person.role.notification_title,
    }


def _trigger_event_dedupe_key(
    identity: event_store.EventIdentity,
    trigger: face_recheck.FinalRecognitionTrigger,
) -> str:
    identity_part = trigger.person_id if trigger.kind == "known" and trigger.person_id else trigger.face_key
    return f"{identity.dedupe_key}:{trigger.face_key}:{trigger.kind}:{identity_part}"


def _final_business_result(
    final_decision: face_recheck.FinalRecognitionDecision,
    fallback: str,
) -> str:
    if final_decision.primary_trigger:
        return final_decision.primary_trigger.kind
    return fallback


def _title_for_person_type(person_type: str | None) -> str:
    if person_type == "member":
        return "😊 会员入场提醒"
    if person_type == "coach":
        return "🧑‍🏫 教练入场提醒"
    if person_type == "staff":
        return "🧑‍💼 员工入场提醒"
    return "人员入场提醒"


def _role_name_for_person_type(person_type: str | None) -> str:
    if person_type == "member":
        return "会员"
    if person_type == "coach":
        return "教练"
    if person_type == "staff":
        return "员工"
    return ""


def _dict_or_skipped(value: Any, reason: str) -> dict[str, Any]:
    return value if isinstance(value, dict) else _notification_skipped(reason)


def _route_face_reco(match_number: int | None, person_info_value: Any) -> str:
    if match_number is not None and match_number == 0:
        return "stranger"
    if not _person_info_empty(person_info_value):
        return "known"
    if match_number is not None and match_number > 0:
        return "parse_error"
    return "stranger"


def _parse_matched_person(person_info_value: Any) -> MatchedPerson:
    person_info = _first_person_info(person_info_value) or {}
    person_id = _first_str(
        person_info.get("uniqueId"),
        person_info.get("UniqueID"),
        person_info.get("personId"),
        person_info.get("PersonID"),
        person_info.get("FaceUUID"),
        person_info.get("faceUUID"),
    )
    name = _first_str(
        person_info.get("name"),
        person_info.get("Name"),
        person_info.get("personName"),
        person_info.get("PersonName"),
        person_info.get("nickName"),
    )
    camera_person_id = _first_str(
        person_info.get("personId"),
        person_info.get("PersonID"),
    )
    ack_person_id = _parse_int(camera_person_id) or 0
    return MatchedPerson(
        name=name or "未知姓名",
        person_id=person_id or "未知ID",
        ack_person_id=ack_person_id,
        camera_person_id=camera_person_id,
        person_name_missing=not bool(name),
        person_id_missing=not bool(person_id),
        role=_resolve_person_role(person_info),
        raw=person_info,
    )


def _resolve_person_role(person_info: dict[str, Any]) -> PersonRole:
    roles = _configured_person_roles()
    id_candidates = _person_group_id_candidates(person_info)
    name_candidates = _person_group_name_candidates(person_info)

    for candidate in id_candidates:
        normalized_candidate = _normalize_group_value(candidate)
        for role in roles:
            normalized_group_id = _normalize_group_value(role.group_id)
            if normalized_group_id and (
                normalized_candidate == normalized_group_id
                or (
                    len(normalized_group_id) >= 16
                    and normalized_group_id in normalized_candidate
                )
            ):
                return role

    for candidate in name_candidates:
        normalized_candidate = _normalize_group_value(candidate)
        for role in roles:
            normalized_group_name = _normalize_group_value(role.group_name)
            if normalized_group_name and normalized_candidate == normalized_group_name:
                return role

    return PersonRole(
        code="unknown",
        name="未知身份",
        group_id=_first_str(*id_candidates),
        group_name=_first_str(*name_candidates),
        notification_title="人员入场提醒",
    )


def _configured_person_roles() -> list[PersonRole]:
    roles: list[PersonRole] = []
    seen_group_ids: set[str] = set()
    for code, id_env, name_env, default_name, title in (
        (
            "members",
            "P6S_FACE_GROUP_MEMBERS_ID",
            "P6S_FACE_GROUP_MEMBERS_NAME",
            "会员",
            "😊 会员入场提醒",
        ),
        (
            "coaches",
            "P6S_FACE_GROUP_COACHES_ID",
            "P6S_FACE_GROUP_COACHES_NAME",
            "教练",
            "🧑‍🏫 教练入场提醒",
        ),
        (
            "staff",
            "P6S_FACE_GROUP_STAFF_ID",
            "P6S_FACE_GROUP_STAFF_NAME",
            "员工",
            "🧑‍💼 员工入场提醒",
        ),
    ):
        group_id = os.environ.get(id_env, "").strip()
        group_name = os.environ.get(name_env, default_name).strip() or default_name
        if group_id:
            roles.append(PersonRole(code, group_name, group_id, group_name, title))
            seen_group_ids.add(_normalize_group_value(group_id))

    legacy_group_id = os.environ.get("P6S_FACE_GROUP_ID", "").strip()
    normalized_legacy_id = _normalize_group_value(legacy_group_id)
    if legacy_group_id and normalized_legacy_id not in seen_group_ids:
        legacy_group_name = (
            os.environ.get("P6S_FACE_GROUP_NAME", "").strip() or "会员"
        )
        roles.append(
            PersonRole(
                code="members",
                name=legacy_group_name,
                group_id=legacy_group_id,
                group_name=legacy_group_name,
                notification_title="😊 会员入场提醒",
            )
        )
    return roles


def _person_group_id_candidates(person_info: dict[str, Any]) -> list[str]:
    return _non_empty_strings(
        person_info.get("personType"),
        person_info.get("PersonType"),
        person_info.get("groupId"),
        person_info.get("GroupId"),
        person_info.get("GroupID"),
        person_info.get("FaceGroupID"),
        person_info.get("FaceGroupId"),
        person_info.get("faceGroupId"),
        person_info.get("faceGroupID"),
    )


def _person_group_name_candidates(person_info: dict[str, Any]) -> list[str]:
    return _non_empty_strings(
        person_info.get("groupName"),
        person_info.get("GroupName"),
        person_info.get("Group"),
        person_info.get("group"),
    )


def _non_empty_strings(*values: Any) -> list[str]:
    strings: list[str] = []
    for value in values:
        text = _first_str(value)
        if text:
            strings.append(text)
    return strings


def _normalize_group_value(value: str) -> str:
    return str(value or "").strip().lower()


def _first_person_info(person_info_value: Any) -> dict[str, Any] | None:
    if isinstance(person_info_value, dict):
        return person_info_value if person_info_value else None
    if isinstance(person_info_value, list):
        for item in person_info_value:
            if isinstance(item, dict) and item:
                return item
    return None


def _person_info_empty(person_info_value: Any) -> bool:
    return _first_person_info(person_info_value) is None


def _decode_named_event_image(
    info: dict[str, Any],
    *,
    kind: str,
    source: str,
) -> tuple[DecodedEventImage | None, str, str]:
    image_info = info.get(source) or {}
    picture = _first_str(image_info.get("picture"), image_info.get("Picture"))
    if not picture:
        return None, "missing", f"{source} has no picture"
    if "," in picture:
        _, picture = picture.split(",", 1)
    compact_picture = "".join(picture.split())
    if not compact_picture:
        return None, "empty", source
    try:
        image_bytes = base64.b64decode(compact_picture, validate=True)
    except (binascii.Error, ValueError):
        return None, "decode_failed", source
    if not image_bytes:
        return None, "empty", source
    expected_md5 = _first_str(
        image_info.get("pictureMd5"),
        image_info.get("PictureMd5"),
        image_info.get("pictureMD5"),
        image_info.get("md5"),
    )
    return DecodedEventImage(kind, source, image_bytes, expected_md5), "decoded", ""


def _save_face_reco_images(
    info: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    root: Path | str | None,
    category: str,
    error_prefix: str,
) -> SavedFaceRecoImages:
    saved = {
        kind: _save_single_face_reco_image(
            info,
            identity=identity,
            root=root,
            category=category,
            error_prefix=error_prefix,
            kind=kind,
            source=source,
        )
        for kind, source in (
            ("background", "BackgroundImage"),
            ("capture", "CaptureImage"),
        )
    }
    return SavedFaceRecoImages(
        background=saved.get("background"),
        capture=saved.get("capture"),
    )


def _save_single_face_reco_image(
    info: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    root: Path | str | None,
    category: str,
    error_prefix: str,
    kind: str,
    source: str,
) -> SavedFaceRecoImage:
    decoded_image, image_status, image_message = _decode_named_event_image(
        info,
        kind=kind,
        source=source,
    )
    if not decoded_image:
        return SavedFaceRecoImage(
            kind=kind,
            source=source,
            stored_image=None,
            created_link=None,
            image_record={
                "status": image_status,
                "source": source,
                "kind": kind,
                "error": image_message,
            },
            link_record=None,
            notify_message=f"{error_prefix}{kind}不可用: {image_status}",
        )

    try:
        stored_image = event_store.save_face_image(
            identity,
            decoded_image.image_bytes,
            source=decoded_image.source,
            expected_md5=decoded_image.expected_md5,
            root=root,
            category=category,
            image_kind=decoded_image.kind,
        )
        created_link = image_links.create_image_link(
            record_dedupe_key=identity.dedupe_key,
            relative_path=stored_image.relative_path,
            content_type=stored_image.content_type,
            created_at=identity.received_at,
            root=root,
        )
        return SavedFaceRecoImage(
            kind=kind,
            source=source,
            stored_image=stored_image,
            created_link=created_link,
            image_record=stored_image.to_dict(),
            link_record=_link_to_dict(created_link),
            notify_message="",
        )
    except event_store.UnsupportedImageTypeError as exc:
        image_status = _image_error_status(str(exc))
        return SavedFaceRecoImage(
            kind=kind,
            source=source,
            stored_image=None,
            created_link=None,
            image_record={
                "status": image_status,
                "source": decoded_image.source,
                "kind": decoded_image.kind,
                "error": str(exc),
            },
            link_record=None,
            notify_message=f"{error_prefix}{kind}保存失败: {image_status}",
        )
    except Exception as exc:
        return SavedFaceRecoImage(
            kind=kind,
            source=source,
            stored_image=None,
            created_link=None,
            image_record={
                "status": "save_failed",
                "source": decoded_image.source,
                "kind": decoded_image.kind,
                "error": type(exc).__name__,
            },
            link_record=None,
            notify_message=f"{error_prefix}{kind}保存或链接生成失败",
        )


def _ack_for_payload(
    payload: dict[str, Any],
    matched_person: MatchedPerson | None,
    stored_image: str | None,
) -> dict[str, Any]:
    operator = str(payload.get("operator") or "")
    if operator == "heartbeat":
        return _heartbeat_ack(payload)
    if operator == "FaceReco":
        return _face_reco_ack(payload, matched_person=matched_person, stored_image=stored_image or "")
    return _generic_ack(operator)


def _heartbeat_ack(payload: dict[str, Any]) -> dict[str, Any]:
    info = payload.get("info") or {}
    return {
        "operator": "heartbeat-Ack",
        "info": {
            "eventId": info.get("eventId", 1),
            "time": event_store.now_local().strftime("%Y%m%dT%H%M%S+08"),
            "eventSendMode": os.environ.get("P6S_EVENT_SEND_MODE", "realTime"),
            "strategy": _event_strategy(),
        },
        "result": {"errorNo": 0, "description": "ok"},
    }


def _face_reco_ack(
    payload: dict[str, Any],
    *,
    matched_person: MatchedPerson | None,
    stored_image: str,
) -> dict[str, Any]:
    info = payload.get("info") or {}
    capture = info.get("CaptureImage") or {}
    return {
        "operator": "FaceReco-Ack",
        "info": {
            "personId": matched_person.ack_person_id if matched_person else 0,
            "uniqueId": matched_person.person_id if matched_person else "",
            "pictureMd5": _first_str(capture.get("pictureMd5"), capture.get("PictureMd5")),
            "storedImage": stored_image,
        },
        "result": {"errorNo": 0, "description": "ok"},
    }


def _generic_ack(operator: str) -> dict[str, Any]:
    return {
        "operator": f"{operator}-Ack" if operator else "Ack",
        "result": {"errorNo": 0, "description": "ok"},
    }


def _event_strategy() -> dict[str, Any]:
    return {
        "passengerStaticsInterval": int(os.environ.get("P6S_PASSENGER_INTERVAL", "2")),
        "heartBeatInterval": int(os.environ.get("P6S_HEARTBEAT_INTERVAL", "30")),
        "isEnableElectronicDefence": False,
        "isCrossBorderDetectEnable": False,
        "isOffDutyDetectEnable": False,
        "isPassengerFlowStaticsEnable": False,
        "isCryScreamDetectEnable": False,
        "isPetDetectEnable": False,
        "isFallDetectEnable": False,
        "isSnapshotEnable": True,
        "isPersonInfoEnable": True,
        "isPersonDetectEnable": False,
        "isCarLicenseSnapshotEnable": False,
        "isCarDetectEnable": False,
        "isTimedSnapshotEnable": False,
        "isGroundLockStatusChangedEnable": False,
        "isStartupReportEnable": True,
        "isAbnormalEventEnable": False,
        "isNonWhitelistCarEnable": False,
        "isMotionDetectEnable": False,
        "isTrafficStatisticsEnable": False,
        "isTrafficStatisticsCarShapeEnable": False,
        "isKey2CallEnable": False,
        "isLicensePlateSurveillanceEnable": False,
        "isFireDetectEventEnable": False,
        "isVideoCoverEventEnable": False,
        "isElectricBikeEventEnable": False,
        "isGasContainerEventEnable": False,
        "isElectronicDefenceV2EventEnable": False,
        "isPeopleNumberStatisticsEventEnable": False,
        "isPeopleNumberOverLimitEventEnable": False,
    }


def _write_record(
    identity: event_store.EventIdentity,
    record: dict[str, Any],
    *,
    root: Path | str | None,
) -> event_store.StoredFile:
    stored_file = event_store.write_processing_record(identity, record, root=root)
    if identity.operator == "FaceReco":
        recognition_monitor.safe_upsert_processing_record_file(stored_file.path, root=root)
    return stored_file


def _representative_image(images: SavedFaceRecoImages) -> SavedFaceRecoImage | None:
    return images.primary() or images.background or images.capture


def _stored_image_path(image: SavedFaceRecoImage | None) -> str:
    if image and image.stored_image:
        return str(image.stored_image.path)
    return ""


def _image_view_url(image: SavedFaceRecoImage | None) -> str | None:
    if image and image.created_link:
        return image.created_link.view_url
    return None


def _image_token_hash(image: SavedFaceRecoImage | None) -> str | None:
    if image and image.created_link:
        return image.created_link.token_hash
    return None


def _image_source(image: SavedFaceRecoImage | None) -> str:
    if image:
        return str(image.image_record.get("source") or "")
    return ""


def _run_face_recheck_for_event(
    *,
    identity: event_store.EventIdentity,
    route_result: str,
    face_images: SavedFaceRecoImages,
    camera_person: dict[str, Any] | None,
    root: Path | str | None,
) -> face_recheck.FaceRecheckResult:
    primary_image = face_images.primary()
    recheck_result = face_recheck.run_face_recheck(
        face_recheck.FaceRecheckInput(
            identity=identity,
            route_result=route_result,  # type: ignore[arg-type]
            camera_person=camera_person,
            primary_image_path=_stored_image_file(primary_image),
            background_image_path=_stored_image_file(face_images.background),
            capture_image_path=_stored_image_file(face_images.capture),
            background_view_url=_image_view_url(face_images.background),
            capture_view_url=_image_view_url(face_images.capture),
        )
    )
    recheck_result = recognition_monitor.attach_face_crops_to_recheck(
        recheck_result,
        identity=identity,
        source_images={
            "background": face_images.background.stored_image if face_images.background else None,
            "capture": face_images.capture.stored_image if face_images.capture else None,
        },
        root=root,
    )
    return recheck_result


def _notify_face_recheck_shadow_for_event(
    *,
    identity: event_store.EventIdentity,
    route_result: str,
    face_images: SavedFaceRecoImages,
    camera_person: dict[str, Any] | None,
    notify: bool,
    recheck_result: face_recheck.FaceRecheckResult,
    final_decision: face_recheck.FinalRecognitionDecision,
) -> dict[str, Any]:
    if not notify:
        return _notification_skipped("notify disabled")
    if not recheck_result.enabled or recheck_result.mode == "off":
        return _notification_skipped("face recheck disabled")
    shadow_result = _safe_notify(
        feishu.notify_face_recheck_shadow,
        device_sn=identity.serial_number,
        event_time=identity.event_time,
        event_id=identity.event_id,
        camera_result=route_result,
        camera_person_summary=camera_person,
        recheck_result=recheck_result.to_dict(),
        final_decision=final_decision.to_dict(),
        background_view_url=_image_view_url(face_images.background),
        capture_view_url=_image_view_url(face_images.capture),
    )
    return shadow_result


def _stored_image_file(image: SavedFaceRecoImage | None) -> Path | None:
    if image and image.stored_image:
        return image.stored_image.path
    return None


def _matched_person_summary(person: MatchedPerson) -> dict[str, Any]:
    return {
        "name": person.name,
        "id": person.person_id,
        "person_id": person.person_id,
        "camera_person_id": person.camera_person_id,
        "role": person.role.code,
        "role_name": person.role.name,
        "group_id": person.role.group_id,
        "group_name": person.role.group_name,
    }


def _notify_result_summary(result: dict[str, Any]) -> dict[str, Any]:
    summary = {
        "ok": bool(result.get("ok")),
        "skipped": bool(result.get("skipped")),
    }
    if "reason" in result:
        summary["reason"] = result.get("reason")
    if isinstance(result.get("status_code"), int):
        summary["status_code"] = result.get("status_code")
    if result.get("error_type"):
        summary["error_type"] = result.get("error_type")
    return summary


def _notify_known_enabled() -> bool:
    value = os.environ.get("P6S_EVENT_NOTIFY_KNOWN_PERSON", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _notify_unknown(
    *,
    notify: bool,
    image_path: Path | None,
    device_sn: str,
    event_time: str,
    event_id: str | int | None,
    storage_path: str,
    view_url: str | None,
    background_view_url: str | None,
    capture_view_url: str | None,
) -> dict[str, Any]:
    if not notify:
        return _notification_skipped("notify disabled")
    return _safe_notify(
        feishu.notify_unknown_face,
        image_path=image_path,
        device_sn=device_sn,
        event_time=event_time,
        event_id=event_id,
        storage_path=storage_path,
        view_url=view_url,
        background_view_url=background_view_url,
        capture_view_url=capture_view_url,
    )


def _notify_error(
    *,
    notify: bool,
    message: str,
    identity: event_store.EventIdentity,
    raw_event_path: Path,
    storage_path: str = "",
    view_url: str | None = "",
    background_view_url: str | None = None,
    capture_view_url: str | None = None,
) -> dict[str, Any]:
    if not notify:
        return _notification_skipped("notify disabled")
    return _safe_notify(
        feishu.notify_event_error,
        message=message,
        device_sn=identity.serial_number,
        event_time=identity.event_time,
        event_id=identity.event_id,
        raw_event_path=str(raw_event_path),
        storage_path=storage_path,
        view_url=view_url,
        background_view_url=background_view_url,
        capture_view_url=capture_view_url,
    )


def _safe_notify(func: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return func(**kwargs)
    except Exception as exc:
        return {"ok": False, "text": type(exc).__name__}


def _notification_skipped(reason: str) -> dict[str, Any]:
    return {"ok": True, "skipped": True, "reason": reason}


def _ack_summary(ack: dict[str, Any]) -> dict[str, Any]:
    result = ack.get("result") or {}
    return {
        "operator": ack.get("operator", ""),
        "errorNo": result.get("errorNo", 0),
    }


def _link_to_dict(link: image_links.CreatedImageLink | None) -> dict[str, Any] | None:
    if not link:
        return None
    return {
        "token_hash": link.token_hash,
        "record_path": str(link.record_path),
        "relative_path": link.relative_path,
        "content_type": link.content_type,
        "created_at": link.created_at.isoformat(),
        "expires_at": link.expires_at.isoformat(),
    }


def _image_error_status(message: str) -> str:
    if "empty" in message:
        return "empty"
    if "larger" in message:
        return "too_large"
    return "unsupported_format"


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_str(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
