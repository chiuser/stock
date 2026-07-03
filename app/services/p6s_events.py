"""P6S event parsing, routing, storage, notification, and Ack generation."""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services import event_store, feishu, image_links


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
    person_name_missing: bool
    person_id_missing: bool
    role: PersonRole
    raw: dict[str, Any]


@dataclass(frozen=True)
class DecodedEventImage:
    source: str
    image_bytes: bytes
    expected_md5: str


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
        return EventHandleResult(
            ack=_ack_for_payload(payload, None, None),
            result="duplicate",
            identity=identity,
            raw_file=raw_file,
            feishu_result=_notification_skipped("duplicate event"),
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
        )
    return _handle_stranger(
        payload,
        identity=identity,
        raw_file=raw_file,
        root=root,
        notify=notify,
        match_number_missing=match_number is None,
    )


def _handle_known_face(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    person_info_value: Any,
    root: Path | str | None,
    notify: bool,
) -> EventHandleResult:
    person = _parse_matched_person(person_info_value)
    ack = _face_reco_ack(payload, matched_person=person, stored_image="")
    feishu_result = _notification_skipped("known notification disabled")
    if notify and _notify_known_enabled():
        feishu_result = _safe_notify(
            feishu.notify_known_face,
            name=person.name,
            person_id=person.person_id,
            device_sn=identity.serial_number,
            event_time=identity.event_time,
            event_id=identity.event_id,
            role_name=person.role.name if person.role.code != "unknown" else "",
            title=person.role.notification_title,
        )

    record_file = _write_record(
        identity,
        {
            "result": "known",
            "matched_person": {
                "name": person.name,
                "id": person.person_id,
                "person_id": person.ack_person_id,
                "person_name_missing": person.person_name_missing,
                "person_id_missing": person.person_id_missing,
                "person_role": person.role.code,
                "person_role_name": person.role.name,
                "person_group_id": person.role.group_id,
                "person_group_name": person.role.group_name,
                "notification_title": person.role.notification_title,
            },
            "image": {"status": "not_saved"},
            "link": None,
            "feishu": feishu_result,
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
        feishu_result=feishu_result,
    )


def _handle_stranger(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    root: Path | str | None,
    notify: bool,
    match_number_missing: bool,
) -> EventHandleResult:
    info = payload.get("info") or {}
    decoded_image, image_status, image_message = _decode_event_image(info)
    stored_image: event_store.StoredImage | None = None
    created_link: image_links.CreatedImageLink | None = None
    feishu_result: dict[str, Any]
    image_record: dict[str, Any]
    link_record: dict[str, Any] | None = None

    if decoded_image:
        try:
            stored_image = event_store.save_stranger_image(
                identity,
                decoded_image.image_bytes,
                source=decoded_image.source,
                expected_md5=decoded_image.expected_md5,
                root=root,
            )
            created_link = image_links.create_image_link(
                record_dedupe_key=identity.dedupe_key,
                relative_path=stored_image.relative_path,
                content_type=stored_image.content_type,
                created_at=identity.received_at,
                root=root,
            )
            image_record = stored_image.to_dict()
            link_record = _link_to_dict(created_link)
            feishu_result = _notify_unknown(
                notify=notify,
                image_path=stored_image.path,
                device_sn=identity.serial_number,
                event_time=identity.event_time,
                event_id=identity.event_id,
                storage_path=str(stored_image.path),
                view_url=created_link.view_url,
            )
        except event_store.UnsupportedImageTypeError as exc:
            image_status = _image_error_status(str(exc))
            image_record = {
                "status": image_status,
                "source": decoded_image.source,
                "error": str(exc),
            }
            feishu_result = _notify_error(
                notify=notify,
                message=f"未匹配人脸图片保存失败: {image_status}",
                identity=identity,
                raw_event_path=raw_file.path,
            )
        except Exception as exc:
            image_record = {
                "status": "save_failed",
                "source": decoded_image.source,
                "error": type(exc).__name__,
            }
            feishu_result = _notify_error(
                notify=notify,
                message="未匹配人脸图片保存或链接生成失败",
                identity=identity,
                raw_event_path=raw_file.path,
            )
    else:
        image_record = {"status": image_status, "source": "", "error": image_message}
        feishu_result = _notify_error(
            notify=notify,
            message=f"未匹配人脸图片不可用: {image_status}",
            identity=identity,
            raw_event_path=raw_file.path,
        )

    ack = _face_reco_ack(
        payload,
        matched_person=None,
        stored_image=str(stored_image.path) if stored_image else "",
    )
    record_file = _write_record(
        identity,
        {
            "result": "stranger",
            "match_number_missing": match_number_missing,
            "matched_person": {"name": "", "id": ""},
            "image": image_record,
            "link": link_record,
            "feishu": feishu_result,
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
        image=stored_image,
        link=created_link,
        feishu_result=feishu_result,
    )


def _handle_parse_error(
    payload: dict[str, Any],
    *,
    identity: event_store.EventIdentity,
    raw_file: event_store.StoredFile,
    root: Path | str | None,
    notify: bool,
    message: str,
) -> EventHandleResult:
    ack = _face_reco_ack(payload, matched_person=None, stored_image="")
    feishu_result = _notify_error(
        notify=notify,
        message=message,
        identity=identity,
        raw_event_path=raw_file.path,
    )
    record_file = _write_record(
        identity,
        {
            "result": "parse_error",
            "error": message,
            "matched_person": {"name": "", "id": ""},
            "image": {"status": "not_saved"},
            "link": None,
            "feishu": feishu_result,
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
        feishu_result=feishu_result,
    )


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
    ack_person_id = _parse_int(
        person_info.get("personId") or person_info.get("PersonID")
    ) or 0
    return MatchedPerson(
        name=name or "未知姓名",
        person_id=person_id or "未知ID",
        ack_person_id=ack_person_id,
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
            "会员入场提醒",
        ),
        (
            "coaches",
            "P6S_FACE_GROUP_COACHES_ID",
            "P6S_FACE_GROUP_COACHES_NAME",
            "教练",
            "教练入场提醒",
        ),
        (
            "staff",
            "P6S_FACE_GROUP_STAFF_ID",
            "P6S_FACE_GROUP_STAFF_NAME",
            "员工",
            "员工入场提醒",
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
                notification_title="会员入场提醒",
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


def _decode_event_image(info: dict[str, Any]) -> tuple[DecodedEventImage | None, str, str]:
    for source in ("CaptureImage", "BackgroundImage", "recognizeImage"):
        image_info = info.get(source) or {}
        picture = _first_str(image_info.get("picture"), image_info.get("Picture"))
        if not picture:
            continue
        if "," in picture:
            _, picture = picture.split(",", 1)
        compact_picture = "".join(picture.split())
        try:
            image_bytes = base64.b64decode(compact_picture, validate=True)
        except (binascii.Error, ValueError):
            return None, "decode_failed", source
        expected_md5 = _first_str(
            image_info.get("pictureMd5"),
            image_info.get("PictureMd5"),
            image_info.get("pictureMD5"),
            image_info.get("md5"),
        )
        return DecodedEventImage(source, image_bytes, expected_md5), "decoded", ""
    return None, "missing", "no image field"


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
    return event_store.write_processing_record(identity, record, root=root)


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
    view_url: str,
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
    )


def _notify_error(
    *,
    notify: bool,
    message: str,
    identity: event_store.EventIdentity,
    raw_event_path: Path,
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
