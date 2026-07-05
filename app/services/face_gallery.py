"""Server-side InsightFace gallery loading and matching helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

PERSON_TYPE_GROUPS: dict[str, tuple[str, str]] = {
    "member": ("会员", "P6S_FACE_GROUP_MEMBERS_ID"),
    "staff": ("员工", "P6S_FACE_GROUP_STAFF_ID"),
    "coach": ("教练", "P6S_FACE_GROUP_COACHES_ID"),
}

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
_P6S_NAMED_IMAGE_RE = re.compile(
    r"^I(?P<name>.+)#S(?P<sex>[^#]+)#T(?P<credential_type>[^#]+)#M(?P<credential_no>[^#]+)\.(?P<ext>jpe?g|png)$",
    re.IGNORECASE,
)
_GALLERY_CACHE: dict[tuple[str, str, float, float], "FaceGalleryIndex"] = {}
_GALLERY_CANDIDATE_LIMIT = 5
_CAMERA_MATCHED_STATUSES = {"name_matched", "id_matched", "name_and_id_matched"}


@dataclass(frozen=True)
class GallerySourcePerson:
    person_id: str
    credential_no: str
    credential_type: str
    name: str
    sex: str
    person_type: Literal["member", "coach", "staff"]
    group_id: str
    group_name: str
    source_filename: str
    source_image_path: str

    def to_manifest_record(self, index: int, quality_flags: list[str]) -> dict[str, Any]:
        return {
            "index": index,
            "person_id": self.person_id,
            "credential_no": self.credential_no,
            "credential_type": self.credential_type,
            "name": self.name,
            "sex": self.sex,
            "person_type": self.person_type,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "source_filename": self.source_filename,
            "source_image_path": self.source_image_path,
            "quality_flags": list(quality_flags),
        }


@dataclass(frozen=True)
class GalleryCandidateResult:
    rank: int
    person_id: str
    credential_no: str
    credential_type: str
    name: str
    sex: str
    person_type: Literal["member", "coach", "staff"]
    group_id: str
    group_name: str
    similarity: float


@dataclass(frozen=True)
class GallerySearchResult:
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
    accepted_threshold: float
    camera_identity_status: Literal[
        "not_compared",
        "name_matched",
        "id_matched",
        "name_and_id_matched",
        "identity_conflict",
        "camera_unknown",
    ]
    candidates: list[GalleryCandidateResult]


@dataclass(frozen=True)
class FaceGalleryIndex:
    embeddings: Any
    records: list[dict[str, Any]]
    manifest: dict[str, Any]

    def match(
        self,
        embedding: Any,
        *,
        similarity_threshold: float,
        camera_match_similarity_threshold: float,
        similarity_margin: float,
        camera_person: dict[str, Any] | None,
    ) -> GallerySearchResult | None:
        np = _import_numpy()
        matrix = np.asarray(self.embeddings, dtype=np.float32)
        if matrix.size == 0:
            return None
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        vector_norm = float(np.linalg.norm(vector))
        if vector.size == 0 or vector_norm <= 0:
            return None
        vector = vector / vector_norm
        similarities = matrix @ vector
        if similarities.size == 0:
            return None

        order = np.argsort(similarities)[::-1]
        best_index = int(order[0])
        best_similarity = float(similarities[best_index])
        second_similarity = (
            float(similarities[int(order[1])]) if len(order) > 1 else None
        )
        record = self.records[best_index]
        camera_identity_status = compare_camera_identity(record, camera_person)
        accepted_threshold = _accepted_threshold(
            similarity_threshold=similarity_threshold,
            camera_match_similarity_threshold=camera_match_similarity_threshold,
            camera_identity_status=camera_identity_status,
        )
        margin_ok = (
            second_similarity is None
            or best_similarity - second_similarity >= similarity_margin
        )
        accepted = best_similarity >= accepted_threshold and margin_ok
        candidates = [
            _candidate_from_record(
                rank=rank,
                record=self.records[int(index)],
                similarity=float(similarities[int(index)]),
            )
            for rank, index in enumerate(order[:_GALLERY_CANDIDATE_LIMIT], start=1)
        ]
        return GallerySearchResult(
            person_id=str(record.get("person_id") or ""),
            credential_no=str(record.get("credential_no") or record.get("person_id") or ""),
            credential_type=str(record.get("credential_type") or ""),
            name=str(record.get("name") or ""),
            sex=str(record.get("sex") or ""),
            person_type=_person_type(record.get("person_type")),
            group_id=str(record.get("group_id") or ""),
            group_name=str(record.get("group_name") or ""),
            similarity=best_similarity,
            second_similarity=second_similarity,
            accepted=accepted,
            accepted_threshold=accepted_threshold,
            camera_identity_status=camera_identity_status,
            candidates=candidates,
        )


def parse_p6s_named_image(
    path: Path,
    *,
    person_type: Literal["member", "coach", "staff"],
    group_id: str = "",
) -> GallerySourcePerson:
    """Parse a P6S-named face image path into gallery identity metadata."""

    if path.suffix.lower() not in _IMAGE_SUFFIXES:
        raise ValueError("unsupported_image_suffix")
    match = _P6S_NAMED_IMAGE_RE.match(path.name)
    if not match:
        raise ValueError("invalid_p6s_filename")
    name = match.group("name").strip()
    sex = match.group("sex").strip()
    credential_type = match.group("credential_type").strip()
    credential_no = match.group("credential_no").strip()
    if not name or not sex or not credential_type or not credential_no:
        raise ValueError("empty_p6s_filename_field")
    group_name, _ = PERSON_TYPE_GROUPS[person_type]
    return GallerySourcePerson(
        person_id=credential_no,
        credential_no=credential_no,
        credential_type=credential_type,
        name=name,
        sex=sex,
        person_type=person_type,
        group_id=group_id,
        group_name=group_name,
        source_filename=path.name,
        source_image_path=str(path),
    )


def load_gallery(
    *,
    gallery_path: str | Path,
    manifest_path: str | Path,
) -> FaceGalleryIndex:
    """Load and cache gallery assets from private runtime files."""

    gallery_file = Path(gallery_path).expanduser()
    manifest_file = Path(manifest_path).expanduser()
    gallery_stat = gallery_file.stat()
    manifest_stat = manifest_file.stat()
    cache_key = (
        str(gallery_file.resolve()),
        str(manifest_file.resolve()),
        gallery_stat.st_mtime,
        manifest_stat.st_mtime,
    )
    cached = _GALLERY_CACHE.get(cache_key)
    if cached:
        return cached

    np = _import_numpy()
    with np.load(gallery_file, allow_pickle=False) as data:
        embeddings = np.asarray(data["embeddings"], dtype=np.float32)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    records = manifest.get("records") or []
    if embeddings.ndim != 2:
        raise ValueError("gallery_embeddings_must_be_2d")
    if len(records) != embeddings.shape[0]:
        raise ValueError("gallery_manifest_record_count_mismatch")
    index = FaceGalleryIndex(
        embeddings=_normalize_rows(embeddings),
        records=[dict(record) for record in records],
        manifest=manifest,
    )
    _GALLERY_CACHE.clear()
    _GALLERY_CACHE[cache_key] = index
    return index


def compare_camera_identity(
    gallery_record: dict[str, Any],
    camera_person: dict[str, Any] | None,
) -> Literal[
    "not_compared",
    "name_matched",
    "id_matched",
    "name_and_id_matched",
    "identity_conflict",
    "camera_unknown",
]:
    if camera_person is None:
        return "camera_unknown"
    gallery_name = _normalize_identity_text(gallery_record.get("name"))
    gallery_ids = {
        _normalize_identity_text(gallery_record.get("person_id")),
        _normalize_identity_text(gallery_record.get("credential_no")),
    }
    gallery_ids.discard("")
    camera_name = _normalize_identity_text(camera_person.get("name"))
    camera_ids = {
        _normalize_identity_text(camera_person.get("id")),
        _normalize_identity_text(camera_person.get("person_id")),
        _normalize_identity_text(camera_person.get("camera_person_id")),
        _normalize_identity_text(camera_person.get("uniqueId")),
        _normalize_identity_text(camera_person.get("credential_no")),
    }
    camera_ids.discard("")
    if not camera_name and not camera_ids:
        return "not_compared"
    name_matched = bool(gallery_name and camera_name and gallery_name == camera_name)
    id_matched = bool(gallery_ids and camera_ids and gallery_ids.intersection(camera_ids))
    if name_matched and id_matched:
        return "name_and_id_matched"
    if id_matched:
        return "id_matched"
    if name_matched:
        return "name_matched"
    return "identity_conflict"


def _accepted_threshold(
    *,
    similarity_threshold: float,
    camera_match_similarity_threshold: float,
    camera_identity_status: str,
) -> float:
    if camera_identity_status in _CAMERA_MATCHED_STATUSES:
        return min(similarity_threshold, camera_match_similarity_threshold)
    return similarity_threshold


def _normalize_rows(embeddings: Any) -> Any:
    np = _import_numpy()
    matrix = np.asarray(embeddings, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms <= 0] = 1.0
    return matrix / norms


def _normalize_identity_text(value: Any) -> str:
    return str(value or "").strip()


def _person_type(value: Any) -> Literal["member", "coach", "staff"]:
    text = str(value or "").strip()
    if text in {"member", "coach", "staff"}:
        return text  # type: ignore[return-value]
    return "member"


def _candidate_from_record(
    *,
    rank: int,
    record: dict[str, Any],
    similarity: float,
) -> GalleryCandidateResult:
    return GalleryCandidateResult(
        rank=rank,
        person_id=str(record.get("person_id") or ""),
        credential_no=str(record.get("credential_no") or record.get("person_id") or ""),
        credential_type=str(record.get("credential_type") or ""),
        name=str(record.get("name") or ""),
        sex=str(record.get("sex") or ""),
        person_type=_person_type(record.get("person_type")),
        group_id=str(record.get("group_id") or ""),
        group_name=str(record.get("group_name") or ""),
        similarity=similarity,
    )


def _import_numpy() -> Any:
    import numpy as np

    return np
