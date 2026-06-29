"""Start the camera management web service."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn


def _load_env_file(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def _resolve_env_file() -> str | None:
    candidates = [
        os.environ.get("CAMERA_ENV_FILE", "").strip(),
        "/etc/camera-face-guard/app.env",
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def _reload_enabled() -> bool:
    value = os.environ.get("CAMERA_RELOAD", "").strip()
    return value.lower() in {"1", "true", "yes"}


if __name__ == "__main__":
    env_file = _resolve_env_file()
    if env_file:
        _load_env_file(env_file)
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=_reload_enabled())
