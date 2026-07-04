"""Build a private InsightFace gallery from P6S-named face image folders."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import warnings
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import face_gallery, face_recheck

PERSON_SOURCES: tuple[tuple[Literal["member", "staff", "coach"], str, str], ...] = (
    ("member", "会员", "styd_member_faces_full_p6s_named"),
    ("staff", "员工", "staff_p6s_named"),
    ("coach", "教练", "teacher_p6s_named"),
)
GROUP_ID_ENV = {
    "member": "P6S_FACE_GROUP_MEMBERS_ID",
    "staff": "P6S_FACE_GROUP_STAFF_ID",
    "coach": "P6S_FACE_GROUP_COACHES_ID",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build InsightFace gallery assets from P6S-named image folders.",
    )
    parser.add_argument(
        "--member-dir",
        default=str(PROJECT_ROOT / "styd_member_faces_full_p6s_named"),
    )
    parser.add_argument(
        "--staff-dir",
        default=str(PROJECT_ROOT / "staff_p6s_named"),
    )
    parser.add_argument(
        "--coach-dir",
        default=str(PROJECT_ROOT / "teacher_p6s_named"),
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--model-root",
        default=str(Path.home() / ".insightface"),
        help="InsightFace model root. Defaults to ~/.insightface.",
    )
    parser.add_argument("--model-name", default="buffalo_l")
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument(
        "--precheck-only",
        action="store_true",
        help="Only parse filenames and report source counts; do not load InsightFace.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Alias for --precheck-only; does not write gallery files.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_sets = _source_sets(args)
    people, report = _collect_sources(source_sets)
    if report["duplicate_count"]:
        print(json.dumps(_public_report(report), ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit("duplicate person_type + person_id found; gallery build stopped")
    if args.precheck_only or args.dry_run:
        print(json.dumps(_public_report(report), ensure_ascii=False, indent=2, sort_keys=True))
        return
    if not people:
        raise SystemExit("no valid P6S-named images found")
    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_report = _build_gallery(
        people,
        source_sets=source_sets,
        output_dir=output_dir,
        args=args,
        precheck_report=report,
    )
    print(json.dumps(_public_report(build_report), ensure_ascii=False, indent=2, sort_keys=True))


def _source_sets(args: argparse.Namespace) -> list[dict[str, Any]]:
    dirs = {
        "member": Path(args.member_dir).expanduser(),
        "staff": Path(args.staff_dir).expanduser(),
        "coach": Path(args.coach_dir).expanduser(),
    }
    sets: list[dict[str, Any]] = []
    for person_type, group_name, default_dir in PERSON_SOURCES:
        directory = dirs.get(person_type) or PROJECT_ROOT / default_dir
        sets.append(
            {
                "person_type": person_type,
                "group_name": group_name,
                "group_id": os.environ.get(GROUP_ID_ENV[person_type], "").strip(),
                "image_dir": str(directory),
            }
        )
    return sets


def _collect_sources(
    source_sets: list[dict[str, Any]],
) -> tuple[list[face_gallery.GallerySourcePerson], dict[str, Any]]:
    people: list[face_gallery.GallerySourcePerson] = []
    invalid_files: list[dict[str, str]] = []
    seen: dict[tuple[str, str], str] = {}
    duplicates: list[dict[str, str]] = []
    source_summary: list[dict[str, Any]] = []

    for source in source_sets:
        person_type = source["person_type"]
        directory = Path(source["image_dir"])
        image_files = _list_image_files(directory)
        valid_count = 0
        for image_path in image_files:
            try:
                person = face_gallery.parse_p6s_named_image(
                    image_path,
                    person_type=person_type,
                    group_id=source.get("group_id", ""),
                )
            except ValueError as exc:
                invalid_files.append(
                    {
                        "person_type": person_type,
                        "path": str(image_path),
                        "reason": str(exc),
                    }
                )
                continue
            valid_count += 1
            key = (person.person_type, person.person_id)
            if key in seen:
                duplicates.append(
                    {
                        "person_type": person.person_type,
                        "person_id": person.person_id,
                        "first": seen[key],
                        "duplicate": str(image_path),
                    }
                )
                continue
            seen[key] = str(image_path)
            people.append(person)
        source_summary.append(
            {
                "person_type": person_type,
                "group_name": source["group_name"],
                "group_id": source.get("group_id", ""),
                "image_dir": str(directory),
                "total_files": len(image_files),
                "valid_files": valid_count,
                "invalid_files": len(image_files) - valid_count,
            }
        )

    return people, {
        "created_at": _now_text(),
        "source_sets": source_summary,
        "total_files": sum(item["total_files"] for item in source_summary),
        "valid_files": sum(item["valid_files"] for item in source_summary),
        "invalid_files": invalid_files,
        "invalid_file_count": len(invalid_files),
        "duplicates": duplicates,
        "duplicate_count": len(duplicates),
        "success_count": 0,
        "failure_count": 0,
        "failures": [],
        "quality_warning_count": 0,
        "quality_warnings": [],
    }


def _build_gallery(
    people: list[face_gallery.GallerySourcePerson],
    *,
    source_sets: list[dict[str, Any]],
    output_dir: Path,
    args: argparse.Namespace,
    precheck_report: dict[str, Any],
) -> dict[str, Any]:
    settings = replace(
        face_recheck.FaceRecheckSettings.from_env(),
        enabled=True,
        mode=face_recheck.FaceRecheckMode.SHADOW,
        model_name=args.model_name,
        model_root=args.model_root,
        provider=args.provider,
    )
    cv2, np, app = face_recheck._runtime(settings)
    embeddings: list[Any] = []
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    quality_warnings: list[dict[str, Any]] = []

    for person in people:
        image_path = Path(person.source_image_path)
        try:
            img = face_recheck._read_image(cv2, np, image_path)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                faces = app.get(img)
            if not faces:
                raise ValueError("no_face")
            if len(faces) > 1:
                raise ValueError("multiple_faces")
            selected_index, selected_face = face_recheck._select_face(faces)
            summary = face_recheck._summarize_face(
                selected_index,
                selected_face,
                img,
                cv2=cv2,
                settings=settings,
                multiple_faces=False,
            )
            embedding = getattr(selected_face, "normed_embedding", None)
            if embedding is None:
                raise ValueError("embedding_missing")
            vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
            if vector.size == 0:
                raise ValueError("embedding_empty")
            embeddings.append(vector)
            records.append(person.to_manifest_record(len(records), summary.quality_flags))
            if summary.quality_flags:
                quality_warnings.append(
                    {
                        "person_type": person.person_type,
                        "person_id": person.person_id,
                        "name": person.name,
                        "source_filename": person.source_filename,
                        "quality_flags": list(summary.quality_flags),
                    }
                )
        except Exception as exc:
            failures.append(
                {
                    "person_type": person.person_type,
                    "person_id": person.person_id,
                    "name": person.name,
                    "source_filename": person.source_filename,
                    "source_image_path": person.source_image_path,
                    "reason": str(exc) or type(exc).__name__,
                    "error_type": type(exc).__name__,
                }
            )

    if not embeddings:
        raise SystemExit("all gallery images failed; no gallery files were written")

    matrix = face_gallery._normalize_rows(np.vstack(embeddings).astype(np.float32))
    manifest = {
        "model_name": settings.model_name,
        "model_sha256": _model_sha256(settings.model_dir),
        "created_at": _now_text(),
        "source_sets": [
            {
                "person_type": source["person_type"],
                "group_name": source["group_name"],
                "group_id": source.get("group_id", ""),
                "image_dir": source["image_dir"],
                "count": sum(
                    1 for record in records if record["person_type"] == source["person_type"]
                ),
            }
            for source in source_sets
        ],
        "records": records,
    }
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d_%H%M%S")
    report = {
        **precheck_report,
        "created_at": manifest["created_at"],
        "model_name": settings.model_name,
        "model_root": str(Path(settings.model_root).expanduser()),
        "output_dir": str(output_dir),
        "gallery_path": str(output_dir / "gallery.npz"),
        "gallery_manifest_path": str(output_dir / "gallery_manifest.json"),
        "build_report_path": str(output_dir / f"build_report_{timestamp}.json"),
        "success_count": len(records),
        "failure_count": len(failures),
        "failures": failures,
        "quality_warning_count": len(quality_warnings),
        "quality_warnings": quality_warnings,
    }
    _write_gallery_assets(output_dir, matrix, manifest, report, timestamp, np)
    return report


def _write_gallery_assets(
    output_dir: Path,
    embeddings: Any,
    manifest: dict[str, Any],
    report: dict[str, Any],
    timestamp: str,
    np: Any,
) -> None:
    gallery_path = output_dir / "gallery.npz"
    manifest_path = output_dir / "gallery_manifest.json"
    report_path = output_dir / f"build_report_{timestamp}.json"
    tmp_gallery = output_dir / f".gallery.npz.tmp-{os.getpid()}"
    tmp_manifest = output_dir / f".gallery_manifest.json.tmp-{os.getpid()}"
    tmp_report = output_dir / f".build_report.json.tmp-{os.getpid()}"

    with tmp_gallery.open("wb") as f:
        np.savez_compressed(
            f,
            embeddings=embeddings,
            person_ids=np.array([record["person_id"] for record in manifest["records"]]),
            person_types=np.array([record["person_type"] for record in manifest["records"]]),
            names=np.array([record["name"] for record in manifest["records"]]),
        )
    tmp_manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_gallery, gallery_path)
    os.replace(tmp_manifest, manifest_path)
    os.replace(tmp_report, report_path)


def _public_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in report.items()
        if key
        not in {
            "failures",
            "invalid_files",
            "duplicates",
            "quality_warnings",
        }
    } | {
        "failure_samples": report.get("failures", [])[:5],
        "invalid_file_samples": report.get("invalid_files", [])[:5],
        "duplicate_samples": report.get("duplicates", [])[:5],
        "quality_warning_samples": report.get("quality_warnings", [])[:5],
    }


def _list_image_files(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def _model_sha256(model_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(model_dir.glob("*.onnx")):
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _now_text() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
