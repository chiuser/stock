"""Validate the local P6S event flow with fixture payloads."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services import p6s_events
from app.services.event_store import RequestMeta

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    with (FIXTURE_DIR / name).open(encoding="utf-8") as f:
        return json.load(f)


async def validate() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
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

    print("P6S event flow fixtures validated")


if __name__ == "__main__":
    asyncio.run(validate())
