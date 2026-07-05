"""InsightFace recheck helpers for P6S FaceReco events."""

from __future__ import annotations

import os
import time
import warnings
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field, replace
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Any, Literal

from app.services import event_store

GalleryPersonType = Literal["member", "coach", "staff", "class_member"]

_FACE_ANALYSIS_SINGLETON: Any | None = None
_FACE_ANALYSIS_KEY: tuple[str, str, str, float] | None = None
_REQUIRED_MODEL_FILES = ("det_10g.onnx", "w600k_r50.onnx")
_MILESTONE_ACTIVE_MODES = {"shadow", "filter", "verify_and_override"}
_INTERVENTION_MODES = {"filter", "verify_and_override"}
_BLOCKING_QUALITY_FLAGS = {
    "low_det_score",
    "face_too_small",
    "blurred",
    "side_face",
    "head_pitch_bad",
}


class FaceRecheckMode(str, Enum):
    OFF = "off"
    SHADOW = "shadow"
    FILTER = "filter"
    VERIFY_AND_OVERRIDE = "verify_and_override"


@dataclass(frozen=True)
class FaceRecheckSettings:
    enabled: bool
    mode: FaceRecheckMode
    model_name: str
    model_root: str
    provider: str
    det_score_threshold: float
    min_face_width: int
    min_face_height: int
    blur_threshold: float
    frontal_max_yaw_score: float
    head_pitch_min: float
    similarity_threshold: float
    camera_match_similarity_threshold: float
    camera_match_gap_threshold: float
    camera_match_rescue_min_face_width: int
    camera_match_rescue_min_face_height: int
    known_extra_unknown_min_face_width: int
    known_extra_unknown_min_face_height: int
    similarity_margin: float
    gallery_path: str
    gallery_manifest_path: str
    fail_open: bool
    timeout_seconds: int

    @classmethod
    def from_env(cls) -> "FaceRecheckSettings":
        return cls(
            enabled=_env_bool("FACE_RECHECK_ENABLED", False),
            mode=_env_mode("FACE_RECHECK_MODE", FaceRecheckMode.SHADOW),
            model_name=os.environ.get("INSIGHTFACE_MODEL_NAME", "buffalo_l").strip()
            or "buffalo_l",
            model_root=os.environ.get("INSIGHTFACE_MODEL_ROOT", "~/.insightface").strip()
            or "~/.insightface",
            provider=os.environ.get("INSIGHTFACE_PROVIDER", "CPUExecutionProvider").strip()
            or "CPUExecutionProvider",
            det_score_threshold=_env_float("FACE_RECHECK_DET_SCORE", 0.55),
            min_face_width=_env_int("FACE_RECHECK_MIN_FACE_WIDTH", 80, minimum=1),
            min_face_height=_env_int("FACE_RECHECK_MIN_FACE_HEIGHT", 80, minimum=1),
            blur_threshold=_env_float("FACE_RECHECK_BLUR_THRESHOLD", 80.0),
            frontal_max_yaw_score=_env_float("FACE_RECHECK_FRONTAL_MAX_YAW_SCORE", 0.35),
            head_pitch_min=_env_float("FACE_RECHECK_HEAD_PITCH_MIN", -45.0),
            similarity_threshold=_env_float("FACE_RECHECK_SIMILARITY_THRESHOLD", 0.50),
            camera_match_similarity_threshold=_env_float(
                "FACE_RECHECK_CAMERA_MATCH_SIMILARITY_THRESHOLD",
                0.30,
            ),
            camera_match_gap_threshold=_env_float(
                "FACE_RECHECK_CAMERA_MATCH_GAP_THRESHOLD",
                0.03,
            ),
            camera_match_rescue_min_face_width=_env_int(
                "FACE_RECHECK_CAMERA_MATCH_RESCUE_MIN_FACE_WIDTH",
                40,
                minimum=1,
            ),
            camera_match_rescue_min_face_height=_env_int(
                "FACE_RECHECK_CAMERA_MATCH_RESCUE_MIN_FACE_HEIGHT",
                50,
                minimum=1,
            ),
            known_extra_unknown_min_face_width=_env_int(
                "FACE_RECHECK_KNOWN_EXTRA_UNKNOWN_MIN_FACE_WIDTH",
                80,
                minimum=1,
            ),
            known_extra_unknown_min_face_height=_env_int(
                "FACE_RECHECK_KNOWN_EXTRA_UNKNOWN_MIN_FACE_HEIGHT",
                80,
                minimum=1,
            ),
            similarity_margin=_env_float("FACE_RECHECK_SIMILARITY_MARGIN", 0.0),
            gallery_path=os.environ.get(
                "FACE_RECHECK_GALLERY_PATH",
                "/var/lib/camera-face-guard/face-gallery/gallery.npz",
            ).strip()
            or "/var/lib/camera-face-guard/face-gallery/gallery.npz",
            gallery_manifest_path=os.environ.get(
                "FACE_RECHECK_GALLERY_MANIFEST_PATH",
                "/var/lib/camera-face-guard/face-gallery/gallery_manifest.json",
            ).strip()
            or "/var/lib/camera-face-guard/face-gallery/gallery_manifest.json",
            fail_open=_env_bool("FACE_RECHECK_FAIL_OPEN", True),
            timeout_seconds=_env_int("FACE_RECHECK_TIMEOUT_SECONDS", 3, minimum=1),
        )

    @property
    def model_dir(self) -> Path:
        return Path(self.model_root).expanduser() / "models" / self.model_name


@dataclass(frozen=True)
class FaceRecheckInput:
    identity: event_store.EventIdentity
    route_result: Literal["known", "stranger", "parse_error"]
    camera_person: dict[str, Any] | None
    primary_image_path: Path | None
    background_image_path: Path | None
    capture_image_path: Path | None
    background_view_url: str | None
    capture_view_url: str | None


@dataclass(frozen=True)
class DetectedFaceSummary:
    index: int
    bbox: tuple[float, float, float, float]
    det_score: float
    width: float
    height: float
    blur_score: float | None
    frontal_score: float | None
    head_pitch: float | None
    quality_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "bbox": [round(value, 3) for value in self.bbox],
            "det_score": round(self.det_score, 6),
            "width": round(self.width, 3),
            "height": round(self.height, 3),
            "blur_score": _rounded_or_none(self.blur_score),
            "frontal_score": _rounded_or_none(self.frontal_score),
            "head_pitch": _rounded_or_none(self.head_pitch),
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True)
class FaceRecheckThresholds:
    det_score_threshold: float
    min_face_width: int
    min_face_height: int
    blur_threshold: float
    frontal_max_yaw_score: float
    head_pitch_min: float
    similarity_threshold: float
    camera_match_similarity_threshold: float
    camera_match_gap_threshold: float
    camera_match_rescue_min_face_width: int
    camera_match_rescue_min_face_height: int
    known_extra_unknown_min_face_width: int
    known_extra_unknown_min_face_height: int
    similarity_margin: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "det_score_threshold": round(self.det_score_threshold, 6),
            "min_face_width": self.min_face_width,
            "min_face_height": self.min_face_height,
            "blur_threshold": round(self.blur_threshold, 6),
            "frontal_max_yaw_score": round(self.frontal_max_yaw_score, 6),
            "head_pitch_min": round(self.head_pitch_min, 6),
            "similarity_threshold": round(self.similarity_threshold, 6),
            "camera_match_similarity_threshold": round(self.camera_match_similarity_threshold, 6),
            "camera_match_gap_threshold": round(self.camera_match_gap_threshold, 6),
            "camera_match_rescue_min_face_width": self.camera_match_rescue_min_face_width,
            "camera_match_rescue_min_face_height": self.camera_match_rescue_min_face_height,
            "known_extra_unknown_min_face_width": self.known_extra_unknown_min_face_width,
            "known_extra_unknown_min_face_height": self.known_extra_unknown_min_face_height,
            "similarity_margin": round(self.similarity_margin, 6),
        }


@dataclass(frozen=True)
class GalleryCandidate:
    rank: int
    person_id: str
    credential_no: str
    credential_type: str
    name: str
    sex: str
    person_type: GalleryPersonType
    group_id: str
    group_name: str
    similarity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "person_id": self.person_id,
            "credential_no": self.credential_no,
            "credential_type": self.credential_type,
            "name": self.name,
            "sex": self.sex,
            "person_type": self.person_type,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "similarity": round(self.similarity, 6),
        }


@dataclass(frozen=True)
class GalleryMatch:
    person_id: str
    credential_no: str
    credential_type: str
    name: str
    sex: str
    person_type: GalleryPersonType
    group_id: str
    group_name: str
    similarity: float
    second_similarity: float | None
    accepted: bool
    accepted_threshold: float
    camera_identity_status: Literal[
        "not_compared",
        "name_matched",
        "id_matched",
        "name_and_id_matched",
        "identity_conflict",
        "camera_unknown",
    ]
    candidates: list[GalleryCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_id": self.person_id,
            "credential_no": self.credential_no,
            "credential_type": self.credential_type,
            "name": self.name,
            "sex": self.sex,
            "person_type": self.person_type,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "similarity": round(self.similarity, 6),
            "second_similarity": _rounded_or_none(self.second_similarity),
            "accepted": self.accepted,
            "accepted_threshold": round(self.accepted_threshold, 6),
            "camera_identity_status": self.camera_identity_status,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class FaceCropSummary:
    relative_path: str | None = None
    content_type: str | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.relative_path:
            return {
                "status": "saved",
                "relative_path": self.relative_path,
                "content_type": self.content_type or "image/jpeg",
            }
        if self.error_type:
            return {"status": "error", "error_type": self.error_type}
        return {"status": "missing"}


@dataclass(frozen=True)
class FaceRecheckFaceResult:
    image_source: Literal["background", "capture"]
    face_index: int
    face_key: str
    selected_face: DetectedFaceSummary | None
    status: Literal["passed", "filtered", "error"]
    reason: str
    gallery_match: GalleryMatch | None
    crop: FaceCropSummary = field(default_factory=FaceCropSummary)
    error_type: str | None = None

    def with_crop(self, crop: FaceCropSummary) -> "FaceRecheckFaceResult":
        return replace(self, crop=crop)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_source": self.image_source,
            "face_index": self.face_index,
            "face_key": self.face_key,
            "selected_face": self.selected_face.to_dict() if self.selected_face else None,
            "status": self.status,
            "reason": self.reason,
            "gallery_match": self.gallery_match.to_dict() if self.gallery_match else None,
            "crop": self.crop.to_dict(),
            "error_type": self.error_type,
        }


@dataclass(frozen=True)
class FaceRecheckResult:
    enabled: bool
    mode: str
    status: Literal["skipped", "passed", "filtered", "error"]
    decision: Literal["allow_original", "suppress", "override_to_known"]
    reason: str
    image_source: Literal["background", "capture", "none"]
    face_count: int
    selected_face: DetectedFaceSummary | None
    gallery_match: GalleryMatch | None
    elapsed_ms: int | None
    error_type: str | None = None
    thresholds: FaceRecheckThresholds | None = None
    faces: list[FaceRecheckFaceResult] = field(default_factory=list)
    primary_face_key: str | None = None
    accepted_face_count: int = 0
    has_identity_conflict: bool = False
    camera_target_face_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "status": self.status,
            "decision": self.decision,
            "reason": self.reason,
            "image_source": self.image_source,
            "face_count": self.face_count,
            "selected_face": self.selected_face.to_dict() if self.selected_face else None,
            "gallery_match": self.gallery_match.to_dict() if self.gallery_match else None,
            "faces": [face.to_dict() for face in self.faces],
            "primary_face_key": self.primary_face_key,
            "accepted_face_count": self.accepted_face_count,
            "has_identity_conflict": self.has_identity_conflict,
            "camera_target_face_status": self.camera_target_face_status,
            "elapsed_ms": self.elapsed_ms,
            "error_type": self.error_type,
            "thresholds": self.thresholds.to_dict() if self.thresholds else None,
        }


@dataclass(frozen=True)
class FinalRecognitionTrigger:
    kind: Literal["known", "stranger"]
    face_key: str
    image_source: str
    face_index: int
    reason: str
    person_type: GalleryPersonType | None = None
    person_id: str | None = None
    name: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    similarity: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "face_key": self.face_key,
            "image_source": self.image_source,
            "face_index": self.face_index,
            "reason": self.reason,
            "person_type": self.person_type,
            "person_id": self.person_id,
            "name": self.name,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "similarity": _rounded_or_none(self.similarity),
        }


@dataclass(frozen=True)
class SuppressedFaceDecision:
    face_key: str
    image_source: str
    face_index: int
    reason: str
    quality_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "face_key": self.face_key,
            "image_source": self.image_source,
            "face_index": self.face_index,
            "reason": self.reason,
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True)
class FinalRecognitionDecision:
    mode: str
    action: Literal["allow_original", "trigger", "suppress"]
    reason: str
    primary_trigger: FinalRecognitionTrigger | None = None
    extra_triggers: list[FinalRecognitionTrigger] = field(default_factory=list)
    suppressed_faces: list[SuppressedFaceDecision] = field(default_factory=list)

    @property
    def primary_and_extra_triggers(self) -> list[FinalRecognitionTrigger]:
        if self.primary_trigger is None:
            return list(self.extra_triggers)
        return [self.primary_trigger, *self.extra_triggers]

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "action": self.action,
            "reason": self.reason,
            "primary_trigger": self.primary_trigger.to_dict() if self.primary_trigger else None,
            "extra_triggers": [trigger.to_dict() for trigger in self.extra_triggers],
            "suppressed_faces": [face.to_dict() for face in self.suppressed_faces],
        }


def run_face_recheck(
    recheck_input: FaceRecheckInput,
    *,
    settings: FaceRecheckSettings | None = None,
) -> FaceRecheckResult:
    cfg = settings or FaceRecheckSettings.from_env()
    started = time.monotonic()
    if not cfg.enabled:
        return _skipped(cfg, "disabled", started)
    if cfg.mode == FaceRecheckMode.OFF:
        return _skipped(cfg, "mode_off", started)

    inactive_mode_reason = ""
    if cfg.mode.value not in _MILESTONE_ACTIVE_MODES:
        inactive_mode_reason = "mode_not_active_in_milestone_1_3"

    if not recheck_input.background_image_path and not recheck_input.capture_image_path:
        return FaceRecheckResult(
            enabled=True,
            mode=cfg.mode.value,
            status="skipped",
            decision="allow_original",
            reason="no_image",
            image_source="none",
            face_count=0,
            selected_face=None,
            gallery_match=None,
            elapsed_ms=_elapsed_ms(started),
            thresholds=_thresholds(cfg),
        )

    background_faces = _analyze_image_faces(
        cfg,
        recheck_input,
        image_path=Path(recheck_input.background_image_path) if recheck_input.background_image_path else None,
        image_source="background",
        inactive_mode_reason=inactive_mode_reason,
    )
    capture_faces: list[FaceRecheckFaceResult] = []
    if _should_analyze_capture(background_faces, recheck_input, cfg):
        capture_faces = _analyze_image_faces(
            cfg,
            recheck_input,
            image_path=Path(recheck_input.capture_image_path) if recheck_input.capture_image_path else None,
            image_source="capture",
            inactive_mode_reason=inactive_mode_reason,
        )
    return _build_event_result(
        cfg,
        faces=background_faces + capture_faces,
        started=started,
        inactive_mode_reason=inactive_mode_reason,
        camera_person=recheck_input.camera_person,
    )


def build_final_recognition_decision(
    *,
    camera_result: str,
    camera_person: dict[str, Any] | None,
    recheck_result: FaceRecheckResult,
) -> FinalRecognitionDecision:
    """Convert recheck facts into the business action used by attendance/Feishu."""

    if (
        not recheck_result.enabled
        or recheck_result.mode == FaceRecheckMode.OFF.value
        or recheck_result.mode not in _INTERVENTION_MODES
    ):
        return FinalRecognitionDecision(
            mode=recheck_result.mode,
            action="allow_original",
            reason=f"mode_{recheck_result.mode}_does_not_intervene",
        )

    triggers: list[FinalRecognitionTrigger] = []
    suppressed: list[SuppressedFaceDecision] = []
    camera_target_available = _has_available_camera_target_face(
        recheck_result,
        camera_person,
    )
    for face in recheck_result.faces:
        if _face_unavailable(face, recheck_result, camera_person):
            suppressed.append(_suppressed_face(face))
            continue
        if _gallery_accepted(face.gallery_match):
            triggers.append(_known_trigger(face))
        elif face.selected_face is not None:
            extra_unknown_reason = _known_event_extra_unknown_suppression_reason(
                face,
                camera_result=camera_result,
                camera_target_available=camera_target_available,
                thresholds=recheck_result.thresholds,
            )
            if extra_unknown_reason:
                suppressed.append(_suppressed_face(face, reason=extra_unknown_reason))
                continue
            triggers.append(_stranger_trigger(face))
        else:
            suppressed.append(_suppressed_face(face))

    triggers = _dedupe_known_triggers(triggers)
    if not triggers:
        return FinalRecognitionDecision(
            mode=recheck_result.mode,
            action="suppress",
            reason=_join_reasons(recheck_result.reason, "no_valid_face_trigger"),
            suppressed_faces=suppressed or [_event_suppression(recheck_result)],
        )

    primary = _select_primary_trigger(
        triggers,
        camera_result=camera_result,
        recheck_result=recheck_result,
    )
    extras = [trigger for trigger in triggers if trigger is not primary]
    return FinalRecognitionDecision(
        mode=recheck_result.mode,
        action="trigger",
        reason="valid_face_decision",
        primary_trigger=primary,
        extra_triggers=extras,
        suppressed_faces=suppressed,
    )


def _analyze_image_faces(
    cfg: FaceRecheckSettings,
    recheck_input: FaceRecheckInput,
    *,
    image_path: Path | None,
    image_source: Literal["background", "capture"],
    inactive_mode_reason: str,
) -> list[FaceRecheckFaceResult]:
    if image_path is None or not image_path.exists():
        return [
            FaceRecheckFaceResult(
                image_source=image_source,
                face_index=0,
                face_key=f"{image_source}:0",
                selected_face=None,
                status="error",
                reason=_join_reasons("image_missing", inactive_mode_reason),
                gallery_match=None,
                error_type="FileNotFoundError",
            )
        ]
    try:
        cv2, np, app = _runtime(cfg)
        img = _read_image(cv2, np, image_path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            raw_faces = app.get(img)
    except Exception as exc:
        return [
            FaceRecheckFaceResult(
                image_source=image_source,
                face_index=0,
                face_key=f"{image_source}:0",
                selected_face=None,
                status="error",
                reason=_join_reasons(_error_reason(exc), inactive_mode_reason),
                gallery_match=None,
                error_type=type(exc).__name__,
            )
        ]
    if not raw_faces:
        return []

    multiple_faces = len(raw_faces) > 1
    results: list[FaceRecheckFaceResult] = []
    for index, face in enumerate(raw_faces):
        summary = _summarize_face(
            index,
            face,
            img,
            cv2=cv2,
            settings=cfg,
            multiple_faces=multiple_faces,
        )
        status = _face_status(summary)
        gallery_match = _match_gallery(cfg, face, recheck_input.camera_person)
        reason = ",".join(summary.quality_flags) if summary.quality_flags else "quality_passed"
        results.append(
            FaceRecheckFaceResult(
                image_source=image_source,
                face_index=index,
                face_key=f"{image_source}:{index}",
                selected_face=summary,
                status=status,
                reason=_join_reasons(reason, inactive_mode_reason),
                gallery_match=gallery_match,
            )
        )
    return results


def _run_single_image_recheck(
    cfg: FaceRecheckSettings,
    recheck_input: FaceRecheckInput,
    *,
    image_path: Path,
    image_source: Literal["background", "capture"],
    inactive_mode_reason: str,
    started: float,
) -> FaceRecheckResult:
    """Compatibility helper used by older tests and one-off validations."""
    faces = _analyze_image_faces(
        cfg,
        recheck_input,
        image_path=image_path,
        image_source=image_source,
        inactive_mode_reason=inactive_mode_reason,
    )
    return _build_event_result(
        cfg,
        faces=faces,
        started=started,
        inactive_mode_reason=inactive_mode_reason,
        camera_person=recheck_input.camera_person,
    )


def _build_event_result(
    cfg: FaceRecheckSettings,
    *,
    faces: list[FaceRecheckFaceResult],
    started: float,
    inactive_mode_reason: str,
    camera_person: dict[str, Any] | None,
) -> FaceRecheckResult:
    if not faces:
        return FaceRecheckResult(
            enabled=True,
            mode=cfg.mode.value,
            status="filtered",
            decision="allow_original",
            reason=_join_reasons("no_face", inactive_mode_reason),
            image_source="none",
            face_count=0,
            selected_face=None,
            gallery_match=None,
            elapsed_ms=_elapsed_ms(started),
            thresholds=_thresholds(cfg),
            faces=[],
            accepted_face_count=0,
            has_identity_conflict=False,
            camera_target_face_status=_camera_target_face_status([], camera_person),
        )

    primary = _select_primary_face_result(faces, camera_person)
    accepted_face_count = sum(1 for face in faces if _gallery_accepted(face.gallery_match))
    has_identity_conflict = any(
        _gallery_accepted(face.gallery_match)
        and face.gallery_match is not None
        and face.gallery_match.camera_identity_status == "identity_conflict"
        for face in faces
    )
    return FaceRecheckResult(
        enabled=True,
        mode=cfg.mode.value,
        status=primary.status,
        decision="allow_original",
        reason=primary.reason,
        image_source=primary.image_source,
        face_count=_event_face_count(faces),
        selected_face=primary.selected_face,
        gallery_match=primary.gallery_match,
        elapsed_ms=_elapsed_ms(started),
        thresholds=_thresholds(cfg),
        faces=faces,
        primary_face_key=primary.face_key,
        accepted_face_count=accepted_face_count,
        has_identity_conflict=has_identity_conflict,
        camera_target_face_status=_camera_target_face_status(faces, camera_person),
    )


def _event_face_count(faces: list[FaceRecheckFaceResult]) -> int:
    background_count = sum(1 for face in faces if face.image_source == "background" and face.selected_face is not None)
    if background_count:
        return background_count
    return sum(1 for face in faces if face.selected_face is not None)


def _face_status(summary: DetectedFaceSummary) -> Literal["passed", "filtered"]:
    return "filtered" if any(flag in _BLOCKING_QUALITY_FLAGS for flag in summary.quality_flags) else "passed"


def _face_unavailable(
    face: FaceRecheckFaceResult,
    recheck_result: FaceRecheckResult,
    camera_person: dict[str, Any] | None,
) -> bool:
    if face.selected_face is None:
        return True
    if face.status == "passed":
        return False
    return not _camera_match_rescued(face, recheck_result.thresholds, camera_person)


def _camera_match_rescued(
    face: FaceRecheckFaceResult,
    thresholds: FaceRecheckThresholds | None,
    camera_person: dict[str, Any] | None,
) -> bool:
    if thresholds is None or camera_person is None:
        return False
    if face.image_source != "capture" or face.selected_face is None:
        return False
    if not _gallery_accepted(face.gallery_match) or not _gallery_identity_matched(face.gallery_match):
        return False
    flags = set(face.selected_face.quality_flags)
    if "face_too_small" not in flags:
        return False
    if flags.intersection({"low_det_score", "blurred", "side_face", "head_pitch_bad"}):
        return False
    return (
        face.selected_face.width >= thresholds.camera_match_rescue_min_face_width
        and face.selected_face.height >= thresholds.camera_match_rescue_min_face_height
    )


def _has_available_camera_target_face(
    recheck_result: FaceRecheckResult,
    camera_person: dict[str, Any] | None,
) -> bool:
    if camera_person is None:
        return False
    return any(
        _gallery_identity_matched(face.gallery_match)
        and not _face_unavailable(face, recheck_result, camera_person)
        for face in recheck_result.faces
    )


def _known_event_extra_unknown_suppression_reason(
    face: FaceRecheckFaceResult,
    *,
    camera_result: str,
    camera_target_available: bool,
    thresholds: FaceRecheckThresholds | None,
) -> str | None:
    if (
        camera_result != "known"
        or not camera_target_available
        or thresholds is None
        or face.selected_face is None
    ):
        return None
    if (
        face.selected_face.width < thresholds.known_extra_unknown_min_face_width
        or face.selected_face.height < thresholds.known_extra_unknown_min_face_height
    ):
        return "extra_unknown_too_small_for_known_event"
    return None


def _known_trigger(face: FaceRecheckFaceResult) -> FinalRecognitionTrigger:
    match = face.gallery_match
    if match is None:
        return _stranger_trigger(face)
    return FinalRecognitionTrigger(
        kind="known",
        face_key=face.face_key,
        image_source=face.image_source,
        face_index=face.face_index,
        reason="gallery_high_confidence_match",
        person_type=match.person_type,
        person_id=match.person_id,
        name=match.name,
        group_id=match.group_id,
        group_name=match.group_name,
        similarity=match.similarity,
    )


def _stranger_trigger(face: FaceRecheckFaceResult) -> FinalRecognitionTrigger:
    return FinalRecognitionTrigger(
        kind="stranger",
        face_key=face.face_key,
        image_source=face.image_source,
        face_index=face.face_index,
        reason="valid_face_without_gallery_match",
    )


def _suppressed_face(face: FaceRecheckFaceResult, *, reason: str | None = None) -> SuppressedFaceDecision:
    flags = list(face.selected_face.quality_flags) if face.selected_face else []
    return SuppressedFaceDecision(
        face_key=face.face_key,
        image_source=face.image_source,
        face_index=face.face_index,
        reason=reason or face.reason or face.status,
        quality_flags=flags,
    )


def _event_suppression(recheck_result: FaceRecheckResult) -> SuppressedFaceDecision:
    return SuppressedFaceDecision(
        face_key="none:0",
        image_source=recheck_result.image_source,
        face_index=0,
        reason=recheck_result.reason or recheck_result.status,
        quality_flags=_reason_flags(recheck_result.reason),
    )


def _reason_flags(reason: str | None) -> list[str]:
    if not reason:
        return []
    return [part for part in str(reason).split(",") if part]


def _dedupe_known_triggers(
    triggers: list[FinalRecognitionTrigger],
) -> list[FinalRecognitionTrigger]:
    deduped: list[FinalRecognitionTrigger] = []
    seen_known: set[tuple[str, str]] = set()
    for trigger in triggers:
        if trigger.kind != "known":
            deduped.append(trigger)
            continue
        key = (trigger.person_type or "", trigger.person_id or "")
        if key in seen_known:
            continue
        seen_known.add(key)
        deduped.append(trigger)
    return deduped


def _select_primary_trigger(
    triggers: list[FinalRecognitionTrigger],
    *,
    camera_result: str,
    recheck_result: FaceRecheckResult,
) -> FinalRecognitionTrigger:
    if camera_result == "known":
        matched_face_keys = {
            face.face_key
            for face in recheck_result.faces
            if _gallery_identity_matched(face.gallery_match)
        }
        for trigger in triggers:
            if trigger.face_key in matched_face_keys:
                return trigger
    for trigger in triggers:
        if trigger.kind == "known":
            return trigger
    return triggers[0]


def _should_analyze_capture(
    background_faces: list[FaceRecheckFaceResult],
    recheck_input: FaceRecheckInput,
    settings: FaceRecheckSettings,
) -> bool:
    if recheck_input.capture_image_path is None:
        return False
    valid_background_faces = [face for face in background_faces if face.selected_face is not None]
    if not valid_background_faces:
        return True
    if len(valid_background_faces) > 1 and recheck_input.route_result == "known":
        return True
    if len(valid_background_faces) == 1:
        match = valid_background_faces[0].gallery_match
        return match is not None and match.similarity < settings.similarity_threshold
    return False


def _select_primary_face_result(
    faces: list[FaceRecheckFaceResult],
    camera_person: dict[str, Any] | None,
) -> FaceRecheckFaceResult:
    valid_faces = [face for face in faces if face.selected_face is not None]
    if not valid_faces:
        return faces[0]

    aligned_accepted = [
        face
        for face in valid_faces
        if _gallery_accepted(face.gallery_match)
        and _gallery_identity_matched(face.gallery_match)
    ]
    if aligned_accepted:
        return max(aligned_accepted, key=_face_match_score)

    accepted = [face for face in valid_faces if _gallery_accepted(face.gallery_match)]
    if accepted:
        return max(accepted, key=_face_match_score)

    camera_candidate = [
        face
        for face in valid_faces
        if _gallery_identity_matched(face.gallery_match)
    ]
    if camera_person and camera_candidate:
        return max(camera_candidate, key=_face_match_score)

    return max(valid_faces, key=_face_selection_score)


def _face_match_score(face: FaceRecheckFaceResult) -> float:
    if face.gallery_match is None:
        return 0.0
    return float(face.gallery_match.similarity)


def _face_selection_score(face: FaceRecheckFaceResult) -> float:
    if face.selected_face is None:
        return 0.0
    return face.selected_face.width * face.selected_face.height * face.selected_face.det_score


def _gallery_accepted(match: GalleryMatch | None) -> bool:
    return match is not None and match.accepted is True


def _gallery_identity_matched(match: GalleryMatch | None) -> bool:
    return match is not None and match.camera_identity_status in {
        "name_matched",
        "id_matched",
        "name_and_id_matched",
    }


def _camera_target_face_status(
    faces: list[FaceRecheckFaceResult],
    camera_person: dict[str, Any] | None,
) -> str:
    if not camera_person:
        return "camera_unknown"
    if not any(face.selected_face is not None for face in faces):
        return "no_face"
    if any(_gallery_accepted(face.gallery_match) and _gallery_identity_matched(face.gallery_match) for face in faces):
        return "accepted_match"
    if any(_gallery_identity_matched(face.gallery_match) for face in faces):
        return "candidate_below_threshold"
    if any(
        _gallery_accepted(face.gallery_match)
        and face.gallery_match is not None
        and face.gallery_match.camera_identity_status == "identity_conflict"
        for face in faces
    ):
        return "identity_conflict"
    return "not_found"


def with_face_crops(
    result: FaceRecheckResult,
    crops: dict[str, FaceCropSummary],
) -> FaceRecheckResult:
    if not crops:
        return result
    return replace(
        result,
        faces=[
            face.with_crop(crops[face.face_key])
            if face.face_key in crops
            else face
            for face in result.faces
        ],
    )


def _legacy_single_image_recheck(
    cfg: FaceRecheckSettings,
    recheck_input: FaceRecheckInput,
    *,
    image_path: Path,
    image_source: Literal["background", "capture"],
    inactive_mode_reason: str,
    started: float,
) -> FaceRecheckResult:
    if not image_path.exists():
        return FaceRecheckResult(
            enabled=True,
            mode=cfg.mode.value,
            status="error",
            decision="allow_original",
            reason=_join_reasons("image_missing", inactive_mode_reason),
            image_source=image_source,
            face_count=0,
            selected_face=None,
            gallery_match=None,
            elapsed_ms=_elapsed_ms(started),
            error_type="FileNotFoundError",
            thresholds=_thresholds(cfg),
        )
    try:
        cv2, np, app = _runtime(cfg)
        img = _read_image(cv2, np, image_path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            faces = app.get(img)
        if not faces:
            return _result(
                cfg,
                status="filtered",
                reason=_join_reasons("no_face", inactive_mode_reason),
                image_source=image_source,
                face_count=0,
                selected_face=None,
                started=started,
            )

        selected_index, selected_face = _select_face(faces)
        summary = _summarize_face(
            selected_index,
            selected_face,
            img,
            cv2=cv2,
            settings=cfg,
            multiple_faces=len(faces) > 1,
        )
        status: Literal["passed", "filtered"] = (
            "filtered"
            if any(flag in _BLOCKING_QUALITY_FLAGS for flag in summary.quality_flags)
            else "passed"
        )
        gallery_match = _match_gallery(cfg, selected_face, recheck_input.camera_person)
        reason = ",".join(summary.quality_flags) if summary.quality_flags else "quality_passed"
        return _result(
            cfg,
            status=status,
            reason=_join_reasons(reason, inactive_mode_reason),
            image_source=image_source,
            face_count=len(faces),
            selected_face=summary,
            gallery_match=gallery_match,
            started=started,
        )
    except Exception as exc:
        return FaceRecheckResult(
            enabled=True,
            mode=cfg.mode.value,
            status="error",
            decision="allow_original",
            reason=_join_reasons(_error_reason(exc), inactive_mode_reason),
            image_source=image_source,
            face_count=0,
            selected_face=None,
            gallery_match=None,
            elapsed_ms=_elapsed_ms(started),
            error_type=type(exc).__name__,
            thresholds=_thresholds(cfg),
        )


def _runtime(settings: FaceRecheckSettings) -> tuple[Any, Any, Any]:
    global _FACE_ANALYSIS_KEY, _FACE_ANALYSIS_SINGLETON
    key = (
        settings.model_name,
        str(Path(settings.model_root).expanduser()),
        settings.provider,
        settings.det_score_threshold,
    )
    if _FACE_ANALYSIS_SINGLETON is not None and _FACE_ANALYSIS_KEY == key:
        cv2, np = _import_cv2_np()
        return cv2, np, _FACE_ANALYSIS_SINGLETON

    cv2, np = _import_cv2_np()
    _ensure_model_files(settings)
    from insightface.app import FaceAnalysis

    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        app = FaceAnalysis(
            name=settings.model_name,
            root=settings.model_root,
            providers=[settings.provider],
        )
        app.prepare(ctx_id=-1, det_thresh=settings.det_score_threshold)
    _FACE_ANALYSIS_SINGLETON = app
    _FACE_ANALYSIS_KEY = key
    return cv2, np, app


def _import_cv2_np() -> tuple[Any, Any]:
    import cv2
    import numpy as np

    return cv2, np


def _ensure_model_files(settings: FaceRecheckSettings) -> None:
    missing = [
        file_name
        for file_name in _REQUIRED_MODEL_FILES
        if not (settings.model_dir / file_name).exists()
    ]
    if missing:
        raise FileNotFoundError(f"model_missing:{','.join(missing)}")


def _read_image(cv2: Any, np: Any, path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError("image_missing")
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        raise ValueError("image_empty")
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("image_read_failed")
    return img


def _image_attempts(
    recheck_input: FaceRecheckInput,
) -> list[tuple[Path, Literal["background", "capture"]]]:
    attempts: list[tuple[Path, Literal["background", "capture"]]] = []
    seen_paths: set[Path] = set()
    for path, source in (
        (recheck_input.background_image_path, "background"),
        (recheck_input.capture_image_path, "capture"),
        (recheck_input.primary_image_path, "capture"),
    ):
        if path:
            normalized_path = Path(path)
            if normalized_path not in seen_paths:
                attempts.append((normalized_path, source))  # type: ignore[arg-type]
                seen_paths.add(normalized_path)
    return attempts


def _should_fallback_to_capture(
    result: FaceRecheckResult,
    recheck_input: FaceRecheckInput,
    settings: FaceRecheckSettings,
) -> bool:
    if result.image_source != "background" or recheck_input.capture_image_path is None:
        return False
    reasons = {reason.strip() for reason in result.reason.split(",") if reason.strip()}
    if "no_face" in reasons:
        return True
    if result.face_count != 1 or result.gallery_match is None:
        return False
    return result.gallery_match.similarity < settings.similarity_threshold


def _select_face(faces: list[Any]) -> tuple[int, Any]:
    def score(item: tuple[int, Any]) -> float:
        _, face = item
        x1, y1, x2, y2 = _bbox(face)
        area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        return area * float(getattr(face, "det_score", 0.0) or 0.0)

    return max(enumerate(faces), key=score)


def _summarize_face(
    index: int,
    face: Any,
    img: Any,
    *,
    cv2: Any,
    settings: FaceRecheckSettings,
    multiple_faces: bool,
) -> DetectedFaceSummary:
    x1, y1, x2, y2 = _bbox(face)
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    det_score = float(getattr(face, "det_score", 0.0) or 0.0)
    blur_score = _blur_score(cv2, img, x1, y1, x2, y2)
    frontal_score = _frontal_score(face)
    head_pitch = _head_pitch(face)
    flags: list[str] = []
    if multiple_faces:
        flags.append("multiple_faces")
    if det_score < settings.det_score_threshold:
        flags.append("low_det_score")
    if width < settings.min_face_width or height < settings.min_face_height:
        flags.append("face_too_small")
    if blur_score is not None and blur_score < settings.blur_threshold:
        flags.append("blurred")
    if frontal_score is not None and frontal_score > settings.frontal_max_yaw_score:
        flags.append("side_face")
    if head_pitch is not None and head_pitch < settings.head_pitch_min:
        flags.append("head_pitch_bad")
    return DetectedFaceSummary(
        index=index,
        bbox=(x1, y1, x2, y2),
        det_score=det_score,
        width=width,
        height=height,
        blur_score=blur_score,
        frontal_score=frontal_score,
        head_pitch=head_pitch,
        quality_flags=flags,
    )


def _bbox(face: Any) -> tuple[float, float, float, float]:
    bbox = getattr(face, "bbox", None)
    if bbox is None:
        return 0.0, 0.0, 0.0, 0.0
    return tuple(float(value) for value in bbox[:4])  # type: ignore[return-value]


def _blur_score(cv2: Any, img: Any, x1: float, y1: float, x2: float, y2: float) -> float | None:
    height, width = img.shape[:2]
    left = max(0, min(width, int(x1)))
    right = max(0, min(width, int(x2)))
    top = max(0, min(height, int(y1)))
    bottom = max(0, min(height, int(y2)))
    if right <= left or bottom <= top:
        return None
    face_crop = img[top:bottom, left:right]
    gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _frontal_score(face: Any) -> float | None:
    kps = getattr(face, "kps", None)
    if kps is None or len(kps) < 3:
        return None
    try:
        left_eye = kps[0]
        right_eye = kps[1]
        nose = kps[2]
        eye_distance = abs(float(right_eye[0]) - float(left_eye[0]))
        if eye_distance <= 0:
            return None
        eye_center_x = (float(left_eye[0]) + float(right_eye[0])) / 2.0
        return abs(float(nose[0]) - eye_center_x) / eye_distance
    except (TypeError, ValueError, IndexError):
        return None


def _head_pitch(face: Any) -> float | None:
    pose = getattr(face, "pose", None)
    if pose is None or len(pose) < 1:
        return None
    try:
        return float(pose[0])
    except (TypeError, ValueError, IndexError):
        return None


def _result(
    settings: FaceRecheckSettings,
    *,
    status: Literal["passed", "filtered"],
    reason: str,
    image_source: Literal["background", "capture", "none"],
    face_count: int,
    selected_face: DetectedFaceSummary | None,
    started: float,
    gallery_match: GalleryMatch | None = None,
) -> FaceRecheckResult:
    return FaceRecheckResult(
        enabled=True,
        mode=settings.mode.value,
        status=status,
        decision="allow_original",
        reason=reason,
        image_source=image_source,
        face_count=face_count,
        selected_face=selected_face,
        gallery_match=gallery_match,
        elapsed_ms=_elapsed_ms(started),
        thresholds=_thresholds(settings),
    )


def _match_gallery(
    settings: FaceRecheckSettings,
    selected_face: Any,
    camera_person: dict[str, Any] | None,
) -> GalleryMatch | None:
    embedding = getattr(selected_face, "normed_embedding", None)
    if embedding is None:
        return None
    try:
        from app.services import face_gallery

        index = face_gallery.load_gallery(
            gallery_path=settings.gallery_path,
            manifest_path=settings.gallery_manifest_path,
        )
        match = index.match(
            embedding,
            similarity_threshold=settings.similarity_threshold,
            camera_match_similarity_threshold=settings.camera_match_similarity_threshold,
            camera_match_gap_threshold=settings.camera_match_gap_threshold,
            similarity_margin=settings.similarity_margin,
            camera_person=camera_person,
        )
    except Exception:
        return None
    if match is None:
        return None
    return GalleryMatch(
        person_id=match.person_id,
        credential_no=match.credential_no,
        credential_type=match.credential_type,
        name=match.name,
        sex=match.sex,
        person_type=match.person_type,
        group_id=match.group_id,
        group_name=match.group_name,
        similarity=match.similarity,
        second_similarity=match.second_similarity,
        accepted=match.accepted,
        accepted_threshold=match.accepted_threshold,
        camera_identity_status=match.camera_identity_status,
        candidates=[
            GalleryCandidate(
                rank=candidate.rank,
                person_id=candidate.person_id,
                credential_no=candidate.credential_no,
                credential_type=candidate.credential_type,
                name=candidate.name,
                sex=candidate.sex,
                person_type=candidate.person_type,
                group_id=candidate.group_id,
                group_name=candidate.group_name,
                similarity=candidate.similarity,
            )
            for candidate in match.candidates
        ],
    )


def _skipped(settings: FaceRecheckSettings, reason: str, started: float) -> FaceRecheckResult:
    return FaceRecheckResult(
        enabled=settings.enabled,
        mode=settings.mode.value,
        status="skipped",
        decision="allow_original",
        reason=reason,
        image_source="none",
        face_count=0,
        selected_face=None,
        gallery_match=None,
        elapsed_ms=_elapsed_ms(started),
        thresholds=_thresholds(settings),
    )


def _thresholds(settings: FaceRecheckSettings) -> FaceRecheckThresholds:
    return FaceRecheckThresholds(
        det_score_threshold=settings.det_score_threshold,
        min_face_width=settings.min_face_width,
        min_face_height=settings.min_face_height,
        blur_threshold=settings.blur_threshold,
        frontal_max_yaw_score=settings.frontal_max_yaw_score,
        head_pitch_min=settings.head_pitch_min,
        similarity_threshold=settings.similarity_threshold,
        camera_match_similarity_threshold=settings.camera_match_similarity_threshold,
        camera_match_gap_threshold=settings.camera_match_gap_threshold,
        camera_match_rescue_min_face_width=settings.camera_match_rescue_min_face_width,
        camera_match_rescue_min_face_height=settings.camera_match_rescue_min_face_height,
        known_extra_unknown_min_face_width=settings.known_extra_unknown_min_face_width,
        known_extra_unknown_min_face_height=settings.known_extra_unknown_min_face_height,
        similarity_margin=settings.similarity_margin,
    )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _join_reasons(*reasons: str) -> str:
    return ";".join(reason for reason in reasons if reason)


def _error_reason(exc: Exception) -> str:
    text = str(exc)
    if text.startswith("model_missing"):
        return text
    if text in {"image_missing", "image_empty", "image_read_failed"}:
        return text
    if isinstance(exc, ImportError):
        return "dependency_missing"
    return "recheck_error"


def _env_mode(name: str, default: FaceRecheckMode) -> FaceRecheckMode:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    try:
        return FaceRecheckMode(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    if minimum is not None and value < minimum:
        return default
    return value


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _rounded_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)
