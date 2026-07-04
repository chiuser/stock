"""InsightFace shadow recheck helpers for P6S FaceReco events.

Milestone 1-3 intentionally only records shadow conclusions. It never
suppresses attendance records or overrides camera identity decisions.
"""

from __future__ import annotations

import os
import time
import warnings
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Any, Literal

from app.services import event_store

_FACE_ANALYSIS_SINGLETON: Any | None = None
_FACE_ANALYSIS_KEY: tuple[str, str, str, float] | None = None
_REQUIRED_MODEL_FILES = ("det_10g.onnx", "w600k_r50.onnx")
_MILESTONE_ACTIVE_MODES = {"shadow"}


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
    similarity_threshold: float
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
            det_score_threshold=_env_float("FACE_RECHECK_DET_SCORE", 0.65),
            min_face_width=_env_int("FACE_RECHECK_MIN_FACE_WIDTH", 80, minimum=1),
            min_face_height=_env_int("FACE_RECHECK_MIN_FACE_HEIGHT", 80, minimum=1),
            blur_threshold=_env_float("FACE_RECHECK_BLUR_THRESHOLD", 80.0),
            frontal_max_yaw_score=_env_float("FACE_RECHECK_FRONTAL_MAX_YAW_SCORE", 0.35),
            similarity_threshold=_env_float("FACE_RECHECK_SIMILARITY_THRESHOLD", 0.50),
            similarity_margin=_env_float("FACE_RECHECK_SIMILARITY_MARGIN", 0.03),
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
            "quality_flags": list(self.quality_flags),
        }


@dataclass(frozen=True)
class GalleryMatch:
    person_id: str
    credential_no: str
    credential_type: str
    name: str
    sex: str
    person_type: Literal["member", "coach", "staff"]
    group_id: str
    group_name: str
    similarity: float
    second_similarity: float | None
    accepted: bool
    camera_identity_status: Literal[
        "not_compared",
        "name_matched",
        "id_matched",
        "name_and_id_matched",
        "identity_conflict",
        "camera_unknown",
    ]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["similarity"] = round(self.similarity, 6)
        data["second_similarity"] = _rounded_or_none(self.second_similarity)
        return data


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
            "elapsed_ms": self.elapsed_ms,
            "error_type": self.error_type,
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

    image_path, image_source = _select_image_path(recheck_input)
    inactive_mode_reason = ""
    if cfg.mode.value not in _MILESTONE_ACTIVE_MODES:
        inactive_mode_reason = "mode_not_active_in_milestone_1_3"

    if image_path is None:
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
        )
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
        blocking_flags = {
            "low_det_score",
            "face_too_small",
            "blurred",
        }
        status: Literal["passed", "filtered"] = (
            "filtered"
            if any(flag in blocking_flags for flag in summary.quality_flags)
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


def _select_image_path(
    recheck_input: FaceRecheckInput,
) -> tuple[Path | None, Literal["background", "capture", "none"]]:
    for path, source in (
        (recheck_input.background_image_path, "background"),
        (recheck_input.capture_image_path, "capture"),
        (recheck_input.primary_image_path, "capture"),
    ):
        if path:
            return Path(path), source  # type: ignore[return-value]
    return None, "none"


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
    return DetectedFaceSummary(
        index=index,
        bbox=(x1, y1, x2, y2),
        det_score=det_score,
        width=width,
        height=height,
        blur_score=blur_score,
        frontal_score=frontal_score,
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
        camera_identity_status=match.camera_identity_status,
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
