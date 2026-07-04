"""Run a local InsightFace shadow recheck against one image."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import face_recheck
from app.services.event_store import EventIdentity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate InsightFace face recheck on a single local image.",
    )
    parser.add_argument("--image", required=True, help="Image path to analyze.")
    parser.add_argument(
        "--model-root",
        default=str(Path.home() / ".insightface"),
        help="InsightFace model root. Defaults to ~/.insightface.",
    )
    parser.add_argument("--model-name", default="buffalo_l")
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument(
        "--mode",
        default="shadow",
        choices=["shadow", "filter", "verify_and_override", "off"],
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = replace(
        face_recheck.FaceRecheckSettings.from_env(),
        enabled=True,
        mode=face_recheck.FaceRecheckMode(args.mode),
        model_name=args.model_name,
        model_root=args.model_root,
        provider=args.provider,
    )
    image_path = Path(args.image).expanduser()
    identity = EventIdentity(
        dedupe_key="local-insightface-recheck",
        operator="FaceReco",
        serial_number="local-poc",
        event_id=image_path.stem or "local-image",
        picture_md5="",
        event_time="",
        event_time_compact=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d%H%M%S"),
        received_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        event_day=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"),
    )
    result = face_recheck.run_face_recheck(
        face_recheck.FaceRecheckInput(
            identity=identity,
            route_result="stranger",
            camera_person=None,
            primary_image_path=image_path,
            background_image_path=image_path,
            capture_image_path=None,
            background_view_url=None,
            capture_view_url=None,
        ),
        settings=settings,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
