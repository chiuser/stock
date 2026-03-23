"""启动 Stock Charts Web 服务。"""
import os
from pathlib import Path

import uvicorn


def _load_env_file(path: str) -> None:
    p = Path(path)
    if not p.exists():
        return
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def _resolve_env_file() -> str | None:
    # 本地开发优先走 STOCK_ENV_FILE，服务器部署则回退到固定的 /etc/stock/stock.env。
    candidates = [
        os.environ.get("STOCK_ENV_FILE", "").strip(),
        "/etc/stock/stock.env",
    ]
    for path in candidates:
        if not path:
            continue
        if Path(path).exists():
            return path
    return None


if __name__ == "__main__":
    env_file = _resolve_env_file()
    if env_file:
        _load_env_file(env_file)
    # 热重载只通过环境变量显式开启，避免生产环境默认进入 reload 模式。
    reload_enabled = os.environ.get("STOCK_RELOAD", "").strip().lower() in {"1", "true", "yes"}
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=reload_enabled)
